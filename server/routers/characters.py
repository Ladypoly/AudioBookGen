"""Characters: list, edit (incl. age variants), and generate portraits/voices.

A character can carry per-age `variants` (slide-dots on the card); each variant
has its own appearance, portrait and voice. Generation for a variant runs the
existing portrait/voice services against a derived Character whose id is
suffixed (``<id>__v<idx>``) so files don't collide with the base.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import threading

from app.core.config import CONFIG
from app.schemas.characters import Character
from app.services import (
    comfy_launcher, ollama_service, portrait_service, project_service, voice_design,
)
from server.jobs import MANAGER

router = APIRouter(prefix="/api/characters", tags=["characters"])

# Guards the read-modify-write of characters.json. Portrait/voice jobs run
# concurrently (2 workers); without this a second job's save clobbers the first
# job's freshly written path (the generated voice/portrait then "disappears").
_CHARS_LOCK = threading.Lock()


def _commit(cid: str, variant: int | None, **fields) -> None:
    """Re-read characters, set fields on the base or a variant, save — atomically
    so concurrent generation jobs don't overwrite each other's results."""
    with _CHARS_LOCK:
        proj = project_service.active()
        characters = project_service.load_characters(proj)
        i = _find(characters, cid)
        target = characters[i] if variant is None else characters[i].variants[variant]
        for k, val in fields.items():
            setattr(target, k, val)
        project_service.save_characters(proj, characters)


def _ensure_render(stage: str) -> None:
    """Free the LLM's VRAM and make sure the (single) ComfyUI is up before a GPU
    render — portrait/voice generation hits ComfyUI directly, so without this it
    fails with a connection-refused if ComfyUI was never launched."""
    ollama_service.unload()
    comfy_launcher.ensure_stage(stage)


# Fields the UI may edit on the base character.
_EDITABLE = {
    "display_name", "gender_guess", "age_band", "role_importance", "voice_hint",
    "personality_notes", "appearance_description", "context", "vocal_traits",
    "appearance_traits", "active", "variants", "sample_line", "tts_workflow",
}


def _proj():
    proj = project_service.active()
    if proj is None:
        raise HTTPException(409, "No project open")
    return proj


def _media_url(p: str | None) -> str | None:
    if not p:
        return None
    try:
        rel = Path(p).resolve().relative_to(CONFIG.projects_root.resolve())
    except (ValueError, OSError):
        return None
    return "/api/media/" + "/".join(rel.parts)


def _serialize(c: Character) -> dict:
    d = c.model_dump(mode="json")
    d["portrait_url"] = _media_url(c.portrait_path)
    d["voice_url"] = _media_url(c.voice_sample)
    for i, v in enumerate(c.variants):
        d["variants"][i]["portrait_url"] = _media_url(v.portrait_path)
        d["variants"][i]["voice_url"] = _media_url(v.voice_sample)
    return d


def _find(characters: list[Character], cid: str) -> int:
    for i, c in enumerate(characters):
        if c.character_id == cid:
            return i
    raise HTTPException(404, f"Character not found: {cid}")


def _derived_for_variant(base: Character, idx: int) -> Character:
    """A Character clone carrying the variant's overrides + a suffixed id, so
    portrait/voice generation writes to distinct files."""
    v = base.variants[idx]
    data = base.model_dump()
    data["character_id"] = f"{base.character_id}__v{idx}"
    data["variants"] = []
    if v.age_band:
        data["age_band"] = v.age_band
    if v.appearance_description:
        data["appearance_description"] = v.appearance_description
    if v.portrait_prompt:
        data["portrait_prompt"] = v.portrait_prompt
    if v.voice_hint:
        data["voice_hint"] = v.voice_hint
    return Character.model_validate(data)


@router.get("")
def list_characters() -> list[dict]:
    proj = _proj()
    ensure_default_trio(proj)            # always show the default male/female/neutral cards
    return [_serialize(c) for c in project_service.load_characters(proj)]


# Shared voices for unnamed one-off speakers (assigned manually to minor
# characters that have no card of their own); varied per line via pitch.
DEFAULT_VOICES = {
    "default_male": ("Default male voice", "male"),
    "default_female": ("Default female voice", "female"),
    "default_neutral": ("Default neutral voice", "ambiguous"),
}


def _make_default(cid: str) -> Character:
    from app.schemas.characters import AgeBand, GenderGuess, RoleImportance
    name, gender = DEFAULT_VOICES[cid]
    return Character(
        character_id=cid, display_name=name,
        gender_guess=GenderGuess(gender), age_band=AgeBand.adult,
        role_importance=RoleImportance.crowd,
        voice_hint="neutral one-off voice", context="generic unnamed speaker",
    )


def ensure_default_trio(proj) -> None:
    """Make sure all three default voices exist in the registry (idempotent)."""
    with _CHARS_LOCK:
        characters = project_service.load_characters(proj)
        existing = {c.character_id for c in characters}
        missing = [cid for cid in DEFAULT_VOICES if cid not in existing]
        if missing:
            characters.extend(_make_default(cid) for cid in missing)
            project_service.save_characters(proj, characters)


def ensure_default_character(proj, cid: str) -> None:
    """Create a single default voice if it's referenced but missing (lazy)."""
    if cid not in DEFAULT_VOICES:
        return
    with _CHARS_LOCK:
        characters = project_service.load_characters(proj)
        if any(c.character_id == cid for c in characters):
            return
        characters.append(_make_default(cid))
        project_service.save_characters(proj, characters)


@router.post("/defaults")
def ensure_defaults() -> list[dict]:
    """Create (if missing) the default one-off voices and return them."""
    proj = _proj()
    ensure_default_trio(proj)
    characters = project_service.load_characters(proj)
    return [_serialize(c) for c in characters if c.character_id in DEFAULT_VOICES]


class UpdateBody(BaseModel):
    # permissive: any subset of editable fields (validated on merge)
    model_config = {"extra": "allow"}


@router.put("/{cid}")
def update_character(cid: str, body: dict) -> dict:
    proj = _proj()
    characters = project_service.load_characters(proj)
    i = _find(characters, cid)
    merged = characters[i].model_dump()
    for k, val in body.items():
        if k in _EDITABLE:
            merged[k] = val
    characters[i] = Character.model_validate(merged)
    project_service.save_characters(proj, characters)
    return _serialize(characters[i])


class MergeBody(BaseModel):
    source: str          # character_id to fold into {cid}, then delete


def _repoint_speaker(proj, old_id: str, new_id: str) -> int:
    """Re-point every script line spoken by old_id to new_id across all chapters.
    Returns the number of lines changed."""
    from app.services import chapter_service
    count = 0
    for info in chapter_service.load_index(proj):
        ch = chapter_service.load_chapter(proj, info["chapter_id"])
        if ch is None:
            continue
        changed = False
        for ln in ch.lines:
            if ln.speaker_id == old_id:
                ln.speaker_id = new_id
                count += 1
                changed = True
        if changed:
            chapter_service.save_chapter(proj, ch)
    return count


@router.post("/{cid}/merge")
def merge_character(cid: str, body: MergeBody) -> dict:
    """Fold `source` into `cid`: the edited character (cid) survives; source's
    aliases/mentions merge in, all its script lines re-point to cid, then it's
    deleted."""
    if cid == body.source:
        raise HTTPException(400, "Cannot merge a character into itself")
    proj = _proj()
    with _CHARS_LOCK:
        characters = project_service.load_characters(proj)
        survivor = next((c for c in characters if c.character_id == cid), None)
        merged = next((c for c in characters if c.character_id == body.source), None)
        if survivor is None or merged is None:
            raise HTTPException(404, "Character not found")
        # fold identity into the survivor (survivor's name/portrait/voice win)
        survivor.aliases = list(dict.fromkeys([*survivor.aliases, merged.display_name, *merged.aliases]))
        survivor.total_mentions += merged.total_mentions
        survivor.spoken_lines += merged.spoken_lines
        survivor.vocal_traits = list(dict.fromkeys([*survivor.vocal_traits, *merged.vocal_traits]))[:8]
        survivor.appearance_traits = list(dict.fromkeys([*survivor.appearance_traits, *merged.appearance_traits]))[:8]
        characters = [c for c in characters if c.character_id != body.source]
        project_service.save_characters(proj, characters)
    repointed = _repoint_speaker(proj, body.source, cid)
    return {**_serialize(survivor), "repointed_lines": repointed}


@router.post("/{cid}/voice")
async def upload_voice(cid: str, file: UploadFile = File(...),
                       variant: int | None = Form(None)) -> dict:
    """Set a custom (cloned) voice from an uploaded audio file — for the base
    character or a specific age variant."""
    proj = _proj()
    characters = project_service.load_characters(proj)
    i = _find(characters, cid)
    c = characters[i]

    ext = Path(file.filename or "voice.wav").suffix.lower() or ".wav"
    vid = c.character_id if variant is None else f"{c.character_id}__v{variant}"
    proj.voices_dir.mkdir(parents=True, exist_ok=True)
    dst = proj.voices_dir / f"{vid}{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    if variant is None:
        c.voice_sample = str(dst)
        c.custom_voice = True
    else:
        if variant >= len(c.variants):
            raise HTTPException(400, "variant index out of range")
        c.variants[variant].voice_sample = str(dst)
        c.variants[variant].custom_voice = True
    project_service.save_characters(proj, characters)
    return _serialize(c)


def _portrait_job(cid: str, variant: int | None):
    def run(ctx):
        proj = project_service.active()
        characters = project_service.load_characters(proj)
        i = _find(characters, cid)
        base = characters[i]
        ctx.busy("Starting ComfyUI…")
        target = base if variant is None else _derived_for_variant(base, variant)
        _ensure_render("image")
        ctx.busy("Rendering portrait…")
        with comfy_launcher.RENDER_LOCK:        # one GPU render at a time (queue)
            out = portrait_service.generate_portrait(target, on_step=lambda *a: None)
        _commit(cid, variant, portrait_path=str(out))
        return {"portrait": _media_url(str(out))}
    return run


def _build_voice(target: Character, description: str | None = None,
                 language: str | None = None) -> str:
    """Design the timbre (Qwen) then speak an in-character intro (Higgs) in the
    book's language. Returns the spoken-intro path — the playable voice sample.
    Caller holds comfy_launcher.RENDER_LOCK."""
    proj = project_service.active()
    timbre = proj.voice_sample_path(target.character_id)   # raw Qwen timbre clip
    sample = proj.preview_path(target.character_id)         # spoken intro (the sample)
    # Use the intro line written at extraction (editable on the card); only call
    # the LLM here if it's missing. Then free Ollama's VRAM before the two
    # ComfyUI renders (Qwen timbre + Higgs speech).
    intro = getattr(target, "sample_line", "") or voice_design.compose_intro_text(target, CONFIG.tts.language)
    ollama_service.unload()
    comfy_launcher.ensure_stage("tts")        # launch ComfyUI if it isn't up yet
    voice_design.design_voice(target, timbre, on_step=lambda *a: None,
                              description=description, language=language)
    voice_design.render_intro_sample(target, timbre, sample,
                                     language=CONFIG.tts.language, text=intro)
    return str(sample)


def _voice_design_job(cid: str, variant: int | None, description: str | None = None,
                      language: str | None = None):
    def run(ctx):
        proj = project_service.active()
        characters = project_service.load_characters(proj)
        i = _find(characters, cid)
        base = characters[i]
        target = base if variant is None else _derived_for_variant(base, variant)
        ctx.busy("Designing voice…")
        with comfy_launcher.RENDER_LOCK:        # one GPU render at a time (queue)
            sample = _build_voice(target, description, language)
        _commit(cid, variant, voice_sample=sample, custom_voice=False)
        return {"voice": _media_url(sample)}
    return run


class GenBody(BaseModel):
    variant: int | None = None


class DesignBody(BaseModel):
    variant: int | None = None
    description: str | None = None     # edited prompt from the voice-design popup
    language: str | None = None


@router.post("/{cid}/portrait")
def generate_portrait(cid: str, body: GenBody) -> dict:
    proj = _proj()
    characters = project_service.load_characters(proj)
    name = characters[_find(characters, cid)].display_name
    job = MANAGER.submit("portrait", f"Portrait · {name}",
                         _portrait_job(cid, body.variant), meta={"project_id": proj.root.name})
    return {"job_id": job.id}


@router.post("/{cid}/voice/design")
def design_voice(cid: str, body: DesignBody) -> dict:
    proj = _proj()
    characters = project_service.load_characters(proj)
    name = characters[_find(characters, cid)].display_name
    job = MANAGER.submit("voice", f"Voice · {name}",
                         _voice_design_job(cid, body.variant, body.description, body.language),
                         meta={"project_id": proj.root.name})
    return {"job_id": job.id}


# --- batch: generate everything that's missing (portraits first, then voices) -

class BatchBody(BaseModel):
    images: bool = True
    voices: bool = True


def _slots(c: Character) -> list[int | None]:
    return [None, *range(len(c.variants))]


def _portrait_of(c: Character, v: int | None) -> str | None:
    return c.portrait_path if v is None else c.variants[v].portrait_path


def _voice_of(c: Character, v: int | None) -> str | None:
    return c.voice_sample if v is None else c.variants[v].voice_sample


def _custom_of(c: Character, v: int | None) -> bool:
    return c.custom_voice if v is None else c.variants[v].custom_voice


def _batch_job(images: bool, voices: bool):
    def run(ctx) -> dict:
        proj = project_service.active()
        characters = project_service.load_characters(proj)
        img: list[tuple[str, int | None]] = []
        voc: list[tuple[str, int | None]] = []
        for c in characters:
            if not c.active:
                continue
            is_default = c.character_id in DEFAULT_VOICES   # voice-only placeholders
            for v in _slots(c):
                p = _portrait_of(c, v)
                if images and not is_default and not (p and Path(p).exists()):
                    img.append((c.character_id, v))
                if voices and not _custom_of(c, v) and not _voice_of(c, v):
                    voc.append((c.character_id, v))
        # Each voice = two GPU steps (design + clone), counted separately so the
        # bar moves smoothly.
        total = len(img) + 2 * len(voc)
        if total == 0:
            return {"generated": 0, "message": "nothing missing"}

        def _base(cid: str) -> Character:
            chars = project_service.load_characters(proj)   # fresh each time (paths change)
            return chars[_find(chars, cid)]

        def _target(cid: str, v: int | None) -> Character:
            base = _base(cid)
            return base if v is None else _derived_for_variant(base, v)

        # Phase 0: make sure every voice has an intro line, WHILE Ollama is still
        # loaded (composing it after the GPU renders would reload the LLM).
        texts: dict[tuple[str, int | None], str] = {}
        if voc:
            ctx.busy("Preparing intro lines…")
            for cid, v in voc:
                t = _target(cid, v)
                texts[(cid, v)] = (getattr(t, "sample_line", "")
                                   or voice_design.compose_intro_text(t, CONFIG.tts.language))

        ctx.busy("Starting ComfyUI…")
        _ensure_render("image")             # launch the single ComfyUI; frees Ollama VRAM
        done = 0

        # 1) portraits
        for cid, v in img:
            if ctx.cancelled:
                break
            t = _target(cid, v)
            ctx.progress(done, total, f"Portrait · {t.display_name}")
            with comfy_launcher.RENDER_LOCK:
                out = portrait_service.generate_portrait(t, on_step=lambda *a: None)
            _commit(cid, v, portrait_path=str(out))
            done += 1

        # 2) ALL voice timbre designs first (Qwen loaded once), then ALL clones
        #    (Higgs loaded once) — avoids reloading both models per character.
        if voc and not ctx.cancelled:
            comfy_launcher.ensure_stage("tts")
            for cid, v in voc:
                if ctx.cancelled:
                    break
                t = _target(cid, v)
                ctx.progress(done, total, f"Voice design · {t.display_name}")
                with comfy_launcher.RENDER_LOCK:
                    voice_design.design_voice(t, proj.voice_sample_path(t.character_id),
                                              on_step=lambda *a: None)
                done += 1
            comfy_launcher.free_vram()      # unload Qwen before loading Higgs (avoid OOM)

            for cid, v in voc:
                if ctx.cancelled:
                    break
                t = _target(cid, v)
                ctx.progress(done, total, f"Voice clone · {t.display_name}")
                timbre = proj.voice_sample_path(t.character_id)
                sample = proj.preview_path(t.character_id)
                with comfy_launcher.RENDER_LOCK:
                    voice_design.render_intro_sample(
                        t, timbre, sample, language=CONFIG.tts.language, text=texts.get((cid, v)))
                _commit(cid, v, voice_sample=str(sample), custom_voice=False)
                done += 1

        ctx.progress(total, total, "done")
        return {"generated": len(img) + len(voc)}

    return run


@router.post("/generate-missing")
def generate_missing(body: BatchBody) -> dict:
    """Generate every missing portrait then every missing voice, in one queued
    job (portraits first). Skips custom/uploaded voices and the default cards'
    portraits."""
    proj = _proj()
    job = MANAGER.submit("batch", "Generate missing portraits & voices",
                         _batch_job(body.images, body.voices),
                         meta={"project_id": proj.root.name})
    return {"job_id": job.id}


# --- voice-design popup: visual selectors + composed prompt ------------------

VOICE_ACCENTS = [
    {"id": "us", "label": "US", "accent": "American English"},
    {"id": "uk", "label": "UK", "accent": "British English"},
    {"id": "au", "label": "AU", "accent": "Australian English"},
    {"id": "ca", "label": "CA", "accent": "Canadian English"},
    {"id": "in", "label": "IN", "accent": "Indian English"},
    {"id": "ie", "label": "IE", "accent": "Irish English"},
    {"id": "za", "label": "ZA", "accent": "South African English"},
    {"id": "neutral", "label": "Neutral", "accent": "neutral English"},
]
VOICE_LANGUAGES = [
    "English", "Chinese", "Japanese", "Korean", "German",
    "French", "Russian", "Portuguese", "Spanish", "Italian",
]
VOICE_OPTIONS = {
    "genders": ["male", "female", "ambiguous"],
    "ages": ["child", "teen", "young_adult", "adult", "middle_aged", "elderly"],
    "pitches": ["very_low", "low", "moderate", "high", "very_high"],
    "speeds": ["very_slow", "slow", "normal", "fast", "very_fast"],
    "energies": ["calm", "soft", "moderate", "energetic", "intense"],
    "emotions": ["neutral", "happy", "sad", "angry", "excited", "fearful",
                 "tender", "serious", "playful"],
    "styles": ["normal", "narration", "conversational", "whisper", "soft",
               "dramatic", "authoritative"],
    "timbres": ["warm", "raspy", "breathy", "smooth", "nasal", "gravelly",
                "bright", "deep", "husky", "clear", "resonant"],
    "languages": VOICE_LANGUAGES,
    "accents": VOICE_ACCENTS,
}


@router.get("/voice/options")
def voice_options() -> dict:
    return VOICE_OPTIONS


class PromptBody(BaseModel):
    variant: int | None = None
    gender: str | None = None
    age: str | None = None
    pitch: str = "moderate"
    speed: str = "normal"
    energy: str = "moderate"
    emotion: str = "neutral"
    style: str = "normal"
    timbre: list[str] = []
    language: str | None = None
    accent: str | None = None          # an accent phrase ("American English")


@router.post("/{cid}/voice/prompt")
def voice_prompt(cid: str, body: PromptBody) -> dict:
    """Compose the Qwen voice-design instruct from the popup's selectors.

    Defaults come from the character (or its variant) when a field is omitted."""
    from app.core.config import CONFIG

    proj = _proj()
    characters = project_service.load_characters(proj)
    c = characters[_find(characters, cid)]
    target = c if body.variant is None else _derived_for_variant(c, body.variant)
    traits = ", ".join(target.vocal_traits[:6]) or target.voice_hint or "natural, clear"
    prompt = voice_design.compose_description(
        gender=body.gender or target.gender_guess.value,
        age=body.age or target.age_band.value,
        accent=body.accent or CONFIG.tts.design_accent,
        traits=traits, context=target.context,
        pitch=body.pitch, speed=body.speed, energy=body.energy,
        emotion=body.emotion, style=body.style, timbre=body.timbre,
        language=body.language)
    return {
        "prompt": prompt,
        "gender": body.gender or target.gender_guess.value,
        "age": body.age or target.age_band.value,
        "accent": body.accent or CONFIG.tts.design_accent,
        "language": body.language or CONFIG.tts.design_language,
    }
