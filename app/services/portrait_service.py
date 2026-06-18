"""Character portrait generation.

Builds a verified Ideogram-4 JSON caption (PLAN Appendix A.2) from a
character's spoiler-safe appearance description, holding a shared
PortraitStyle constant across the whole cast for series consistency, then
renders it through ComfyUI.

The JSON caption is the valuable, engine-correct artifact and is built fully
here; rendering depends on a user-provided ComfyUI workflow template.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from app.core.config import CONFIG, PortraitStyle
from app.schemas.characters import Character
from app.schemas.style import StyleBible
from app.services import comfy_service, project_service

logger = logging.getLogger(__name__)

# Active book Style Bible — held identical across the whole cast for a unified,
# book-fitting look. Set after extraction; falls back to the generic default.
_active_bible: StyleBible | None = None


def set_style_bible(bible: StyleBible | None) -> None:
    global _active_bible
    _active_bible = bible


def _scrub_names(text: str, char: Character) -> str:
    """Remove the character's name/aliases so Ideogram's safety filter does not
    treat the portrait as a named real person."""
    import re

    for name in [char.display_name, *char.aliases]:
        for token in name.split():
            if len(token) > 2:
                text = re.sub(rf"\b{re.escape(token)}\b", "the character", text)
    # collapse runs like "the character the character" -> "the character"
    text = re.sub(r"(the character\s+)+", "the character ", text).strip()
    return text[:1].upper() + text[1:] if text else text


def _subject_description(char: Character) -> str:
    """Spoiler-safe, name-free visual description for the portrait subject."""
    if char.appearance_description:
        return _scrub_names(char.appearance_description, char)
    bits: list[str] = []
    if char.age_band.value != "unknown":
        bits.append(char.age_band.value.replace("_", " "))
    if char.gender_guess.value != "unknown":
        bits.append(char.gender_guess.value)
    looks = ", ".join(char.appearance_traits) if char.appearance_traits else "plain features"
    who = " ".join(bits) or "person"
    return f"A portrait of a {who} with {looks}."


def build_caption(char: Character, style: PortraitStyle | None = None) -> dict:
    """Build the Ideogram-4 JSON caption (strict key order per Appendix A.2).

    Visual style comes from the active book Style Bible (so all characters
    match the book); framing/size come from PortraitStyle.
    """
    style = style or CONFIG.portrait_style
    bible = _active_bible
    y0, x0, y1, x1 = style.subject_bbox
    if bible is not None:
        aesthetics, lighting, medium = bible.aesthetics, bible.lighting, bible.medium
        art_style, palette, background = bible.art_style, list(bible.color_palette), bible.background
    else:
        aesthetics, lighting, medium = style.aesthetics, style.lighting, style.medium
        art_style, palette, background = style.art_style, list(style.color_palette), style.background
    # NOTE: never put the character's name in the caption. Ideogram's safety
    # filter blocks generating named individuals (deepfake protection) and
    # returns an "Image blocked by Safety filter" placeholder. Describe by
    # appearance only; the name lives in the filename, not the prompt.
    return {
        "high_level_description": "A fictional character portrait, head and shoulders.",
        "style_description": {
            "aesthetics": aesthetics,
            "lighting": lighting,
            "medium": medium,
            "art_style": art_style,
            "color_palette": palette,
        },
        "compositional_deconstruction": {
            "background": background,
            "elements": [
                {
                    "type": "obj",
                    "bbox": [y0, x0, y1, x1],
                    "desc": _subject_description(char),
                }
            ],
        },
    }


def caption_to_prompt(caption: dict) -> str:
    """Serialize per Ideogram guidance (compact, unicode-preserving)."""
    return json.dumps(caption, separators=(",", ":"), ensure_ascii=False)


def portrait_path(char: Character) -> Path:
    """Save into the active book's project folder when one is open."""
    proj = project_service.active()
    if proj is not None:
        return proj.portrait_path(char)
    return CONFIG.portraits_dir / f"{char.character_id}.png"


def _clothing_from_traits(char: Character) -> str:
    """Pull any clothing the text mentioned out of the appearance traits."""
    keys = ("coat", "shirt", "dress", "uniform", "jacket", "hat", "suit", "robe",
            "kleid", "mantel", "jacke", "hemd", "anzug", "uniform", "hut", "cloak",
            "gown", "armor", "armour", "scarf", "tie", "gloves", "boots")
    hits = [t for t in char.appearance_traits if any(k in t.lower() for k in keys)]
    return ", ".join(hits)


def _style_prefix() -> str:
    """FIXED art-style lead-in, identical for the whole cast (consistency)."""
    b = _active_bible
    if b is not None:
        return f"{b.art_style}, {b.aesthetics}, {b.lighting}"
    s = CONFIG.portrait_style
    return f"{s.art_style}, {s.aesthetics}, {s.lighting}"


def _style_suffix() -> str:
    """FIXED trailing constraints, identical for the whole cast (incl. casting,
    so every character matches the book's ethnicity/look — not the model bias)."""
    b = _active_bible
    palette = ", ".join(b.color_palette if b is not None else CONFIG.portrait_style.color_palette)
    casting = b.casting if b is not None else "predominantly European features, varied and natural"
    return (
        f"{casting}. head and shoulders portrait, single subject, centered, "
        "ordinary person, natural imperfect features, not a fashion model, "
        f"softly blurred out-of-focus background. Colour palette: {palette}. "
        "stylized illustrated artwork, painterly, visible brushwork, NOT "
        "photorealistic, not a photograph, consistent illustration style, "
        "no text, no watermark"
    )


def build_zimage_prompt(char: Character, style: PortraitStyle | None = None) -> str:
    """Natural-language portrait prompt for Z-Image (not JSON). Uses the book's
    Style Bible so the whole cast matches; name-free for safety.

    Explicitly sets casting (ethnicity/look), full clothing and wardrobe so the
    model doesn't default to Asian faces / bare or plain-shirt subjects."""
    style = style or CONFIG.portrait_style
    bible = _active_bible
    if bible is not None:
        art, aesth, light = bible.art_style, bible.aesthetics, bible.lighting
        palette = ", ".join(bible.color_palette)
        casting, setting = bible.casting, bible.setting
        bg_choices = bible.background_variants or [bible.background]
        wardrobe_choices = bible.wardrobe_variants or [bible.wardrobe]
    else:
        art, aesth, light = style.art_style, style.aesthetics, style.lighting
        palette = ", ".join(style.color_palette)
        casting = "predominantly European features, varied and natural"
        setting = "contemporary"
        bg_choices = ["softly blurred atmospheric backdrop"]
        wardrobe_choices = ["ordinary everyday clothing"]

    # Per-character pick so backgrounds and outfits vary across the cast.
    seed = _stable_seed(char.character_id)
    background = bg_choices[seed % len(bg_choices)]
    wardrobe = wardrobe_choices[(seed // 7) % len(wardrobe_choices)]

    subject = _subject_description(char)
    clothes = _clothing_from_traits(char) or wardrobe
    return (
        f"{art}, {aesth}. Character portrait, head and shoulders, of an ordinary "
        f"real-looking fictional person in a {setting} setting, natural average "
        f"imperfect features, candid and authentic, NOT a fashion model. "
        f"{subject} {casting}. Fully clothed, wearing {clothes}. {light}. "
        f"Background: {background}, softly blurred and out of focus so the person "
        f"stays the subject. Colour palette: {palette}. Single subject, centered, "
        f"realistic, documentary photography feel, no text, no watermark."
    )


def generate_portrait(char: Character, style: PortraitStyle | None = None, on_step=None) -> Path:
    """Render the portrait via ComfyUI. Returns the saved image path.

    Prompt format depends on the configured backend: Z-Image = natural language
    (+ negative prompt); Ideogram = JSON caption (no negative node).
    """
    style = style or CONFIG.portrait_style
    out = portrait_path(char)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Random render seed each time, so re-generating a portrait that doesn't
    # quite fit yields a fresh variation (the scene/outfit stay stable — those
    # derive from the character id; only the sampler noise changes).
    render_seed = random.randint(0, 2**31 - 1)

    if CONFIG.comfy.portrait_backend == "z_image":
        casting = _active_bible.casting if _active_bible is not None \
            else "predominantly European Caucasian features"
        if char.portrait_prompt:
            # LLM wrote only the subject; wrap it in a FIXED style block that is
            # identical for every character. Casting is stated up front AND in
            # the suffix because Z-Image strongly defaults to Asian faces.
            subject = _scrub_names(char.portrait_prompt, char)
            positive = (
                f"{_style_prefix()}. A character with {casting}. {subject}. "
                f"{_style_suffix()}"
            )
        else:
            positive = build_zimage_prompt(char, style)
        negative = _ethnicity_negative(style.negative_prompt, casting)
        record: dict = {"backend": "z_image", "positive_prompt": positive,
                        "negative_prompt": negative, "seed": render_seed}
        replacements: dict[str, object] = {
            "{positive_prompt}": positive,
            "{negative_prompt}": negative,
            "{filename_prefix}": char.character_id,
            "{seed}": render_seed,
        }
    else:  # ideogram JSON caption
        caption = build_caption(char, style)
        positive = caption_to_prompt(caption)
        record = {"backend": "ideogram", "caption": caption,
                  "positive_prompt": positive, "seed": render_seed}
        replacements = {
            "{positive_prompt}": positive,
            "{filename_prefix}": char.character_id,
            "{seed}": render_seed,
        }

    # Save the exact prompt next to the image for inspection/repro.
    out.with_suffix(".json").write_text(
        json.dumps({"character_id": char.character_id, **record}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    comfy_service.run_workflow(CONFIG.comfy.portrait_workflow, replacements, out, on_step=on_step)
    return out


def _ethnicity_negative(base: str, casting: str) -> str:
    """Adaptively counter Z-Image's Asian-face bias only when the book's casting
    is European/Western (not hardcoded, so an Asian-set book is unaffected)."""
    c = casting.lower()
    if any(w in c for w in ("europ", "caucasian", "western", "white")) and "asian" not in c:
        return base + ", east asian, asian features, chinese, japanese, korean"
    return base


def _stable_seed(text: str) -> int:
    """Deterministic non-negative seed from a string (avoids PYTHONHASHSEED)."""
    import hashlib

    return int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**31)
