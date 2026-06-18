"""Character extraction map-reduce (spoiler-safe).

MAP   : per chunk -> CharacterMention list (LLM, enum-locked, firewall prompt)
GROUP : code-side merge of identical surface forms (sum mentions, union traits)
REDUCE: LLM alias-merge + neutral voice_hint / personality_notes
ROLE  : code-side role_importance from total mention counts (no LLM plot judgement)

See PLAN Appendix A.3.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable

from app.core import prompts
from app.core.config import CONFIG
from app.schemas.characters import (
    AgeBand,
    Character,
    CharacterMention,
    GenderGuess,
    MapResult,
    PortraitPromptResult,
    ReduceResult,
    RegistryCharacter,
    RoleImportance,
    WebEnrichment,
)
from app.schemas.style import StyleBible
from app.services import ollama_service, research_service

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]
CancelCb = Callable[[], bool]
PartialCb = Callable[[list["Character"]], None]

_NARRATOR_NAMES = {"erzähler", "erzaehler", "narrator", "narration"}


_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _slug(name: str) -> str:
    s = name.lower().translate(_UMLAUT)            # Erzähler -> erzaehler
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "char"


# --- MAP ---------------------------------------------------------------------


def map_chunk(chunk_text: str) -> list[CharacterMention]:
    prompt = prompts.render("character_map_prompt", chunk_text=chunk_text)
    result = ollama_service.generate_json(prompt, MapResult)
    return result.mentions


# --- GROUP (code-side) -------------------------------------------------------


def _majority(values: Iterable[str]) -> str | None:
    counts = Counter(v for v in values if v and v != "unknown")
    return counts.most_common(1)[0][0] if counts else None


def group_mentions(mentions: list[CharacterMention]) -> list[RegistryCharacter]:
    """Merge identical surface names (case-insensitive) before the reduce pass."""
    buckets: dict[str, list[CharacterMention]] = {}
    for m in mentions:
        key = m.surface_name.strip().lower()
        if not key:
            continue
        buckets.setdefault(key, []).append(m)

    grouped: list[RegistryCharacter] = []
    for items in buckets.values():
        traits: list[str] = []
        looks: list[str] = []
        for it in items:
            traits.extend(it.vocal_traits)
            looks.extend(it.appearance_traits)
        gender = _majority(i.gender_guess.value for i in items)
        age = _majority(i.age_band.value for i in items)
        ctxs = [i.context.strip() for i in items if i.context.strip()]
        context = max(set(ctxs), key=ctxs.count) if ctxs else ""   # most common role/where
        grouped.append(
            RegistryCharacter(
                display_name=items[0].surface_name.strip(),
                gender_guess=GenderGuess(gender) if gender else GenderGuess.unknown,
                age_band=AgeBand(age) if age else AgeBand.unknown,
                vocal_traits=sorted(set(traits)),
                appearance_traits=sorted(set(looks)),
                context=context,
                total_mentions=sum(i.mention_count for i in items),
                spoken_lines=sum(i.spoken_lines for i in items),
            )
        )
    grouped.sort(key=lambda c: c.total_mentions, reverse=True)
    return grouped


# --- REDUCE ------------------------------------------------------------------


def reduce_characters(grouped: list[RegistryCharacter]) -> list[RegistryCharacter]:
    candidates = [
        {
            "surface_name": c.display_name,
            "gender_guess": c.gender_guess.value,
            "age_band": c.age_band.value,
            "vocal_traits": c.vocal_traits,
            "appearance_traits": c.appearance_traits,
            "total_mentions": c.total_mentions,
        }
        for c in grouped
    ]
    prompt = prompts.render(
        "character_registry_prompt",
        candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
    )
    result = ollama_service.generate_json(prompt, ReduceResult)
    return result.characters


# --- RECONCILE (code-side, authoritative counts) -----------------------------


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9äöüÄÖÜß]+", name.lower()) if len(t) > 2}


def reconcile(
    reduced: list[RegistryCharacter], grouped: list[RegistryCharacter]
) -> list[RegistryCharacter]:
    """Rebuild authoritative counts from the grouped data and re-add anything
    the LLM reduce dropped.

    The reduce LLM only proposes alias merges + descriptions; it must NOT own the
    character list or counts (it hallucinates 0 mentions and collapses the cast).
    Every grouped candidate is matched (by shared name token) into a canonical
    character; counts are summed from grouped; unmatched candidates survive as
    their own characters so nobody is lost.
    """
    canon = [
        (rc, _name_tokens(rc.display_name) | {t for a in rc.aliases for t in _name_tokens(a)})
        for rc in reduced
    ]
    for rc in reduced:
        rc.total_mentions = 0
        rc.spoken_lines = 0

    leftovers: list[RegistryCharacter] = []
    for g in grouped:
        gt = _name_tokens(g.display_name)
        match = next((rc for rc, ct in canon if gt & ct), None)
        if match is None:
            leftovers.append(g)
            continue
        match.total_mentions += g.total_mentions
        match.spoken_lines += g.spoken_lines
        match.vocal_traits = sorted(set(match.vocal_traits) | set(g.vocal_traits))
        match.appearance_traits = sorted(set(match.appearance_traits) | set(g.appearance_traits))
    return reduced + leftovers


def _mergeable(a: str, b: str) -> bool:
    """True if two surface names plausibly denote the same character:
    one is a prefix of the other ("Jeff" / "Jeff Baker", "Tim" / "Timothy")
    or their name-token sets are subset-related."""
    la, lb = a.lower().strip(), b.lower().strip()
    if len(la) >= 3 and len(lb) >= 3 and (lb.startswith(la) or la.startswith(lb)):
        return True
    ta, tb = _name_tokens(a), _name_tokens(b)
    return bool(ta and tb and (ta <= tb or tb <= ta))


def _absorb(canon: RegistryCharacter, other: RegistryCharacter) -> None:
    canon.total_mentions += other.total_mentions
    canon.spoken_lines += other.spoken_lines
    canon.vocal_traits = sorted(set(canon.vocal_traits) | set(other.vocal_traits))
    canon.appearance_traits = sorted(set(canon.appearance_traits) | set(other.appearance_traits))
    if not canon.context and other.context:        # keep whichever has context
        canon.context = other.context
    if other.display_name not in canon.aliases and other.display_name != canon.display_name:
        canon.aliases.append(other.display_name)
    canon.aliases = sorted(set(canon.aliases) | set(other.aliases))


def code_merge(chars: list[RegistryCharacter]) -> list[RegistryCharacter]:
    """Deterministic alias merge (no LLM). Longer names are canonical, so
    "Jeff" folds into "Jeff Baker" and "Tim" into "Timothy"."""
    ordered = sorted(chars, key=lambda c: -len(c.display_name))
    result: list[RegistryCharacter] = []
    for c in ordered:
        canon = next((r for r in result if _mergeable(r.display_name, c.display_name)), None)
        if canon is not None:
            _absorb(canon, c)
        else:
            result.append(c)
    return result


def _who(age: str, gender: str) -> str:
    """A natural noun phrase for age+gender (e.g. 'young boy', 'elderly woman')."""
    if age == "child":
        return {"male": "young boy", "female": "young girl"}.get(gender, "child")
    if age == "teen":
        return {"male": "teenage boy", "female": "teenage girl"}.get(gender, "teenager")
    g = {"male": "man", "female": "woman"}.get(gender, "person")
    a = {"young_adult": "young ", "elderly": "elderly "}.get(age, "")
    return f"{a}{g}".strip()


def _article(phrase: str) -> str:
    return "An" if phrase[:1].lower() in "aeiou" else "A"


def build_descriptions(chars: list[RegistryCharacter]) -> None:
    """Build clean, deterministic voice_hint + appearance_description from the
    collected traits — avoids the LLM rambling / echoing the prompt."""
    for c in chars:
        if not c.voice_hint and c.vocal_traits:
            c.voice_hint = ", ".join(c.vocal_traits[:4])
        if not c.appearance_description:
            who = _who(c.age_band.value, c.gender_guess.value)
            looks = ", ".join(c.appearance_traits[:5])
            c.appearance_description = (
                f"{_article(who)} {who} with {looks}." if looks else f"{_article(who)} {who}."
            )


def speaking_only(chars: list[RegistryCharacter]) -> list[RegistryCharacter]:
    """Keep only speaking roles (+ the narrator). Falls back to all if the model
    reported no spoken lines at all (so we never show an empty cast)."""
    def is_narrator(c: RegistryCharacter) -> bool:
        names = {c.display_name.lower(), *(a.lower() for a in c.aliases)}
        return bool(names & _NARRATOR_NAMES)

    speakers = [c for c in chars if c.spoken_lines > 0 or is_narrator(c)]
    if not any(c.spoken_lines > 0 for c in chars):
        return chars  # model gave no dialogue counts — don't nuke the cast
    return speakers


# --- ROLE (code-side) --------------------------------------------------------


def assign_roles(chars: list[RegistryCharacter]) -> list[Character]:
    if not chars:
        return []
    max_mentions = max(c.total_mentions for c in chars) or 1
    cfg = CONFIG.extraction
    final: list[Character] = []
    used_ids: set[str] = set()

    for c in chars:
        ratio = c.total_mentions / max_mentions
        names = {c.display_name.lower(), *(a.lower() for a in c.aliases)}
        if names & _NARRATOR_NAMES:
            role = RoleImportance.narrator
        elif ratio >= cfg.main_ratio:
            role = RoleImportance.main
        elif ratio >= cfg.secondary_ratio:
            role = RoleImportance.secondary
        elif ratio >= cfg.minor_ratio:
            role = RoleImportance.minor
        else:
            role = RoleImportance.crowd

        cid = base = _slug(c.display_name)
        i = 1
        while cid in used_ids:
            i += 1
            cid = f"{base}_{i}"
        used_ids.add(cid)

        final.append(
            Character(
                character_id=cid,
                role_importance=role,
                **c.model_dump(),
            )
        )

    order = {
        RoleImportance.narrator: 0,
        RoleImportance.main: 1,
        RoleImportance.secondary: 2,
        RoleImportance.minor: 3,
        RoleImportance.crowd: 4,
    }
    final.sort(key=lambda c: (order[c.role_importance], -c.total_mentions))
    return final


# --- Orchestration -----------------------------------------------------------


def extract_characters(
    chunks: list[str],
    progress: ProgressCb | None = None,
    is_cancelled: CancelCb | None = None,
    partial: PartialCb | None = None,
    project: "object | None" = None,
) -> list[Character]:
    """Run the full map-reduce over pre-chunked text.

    `progress(done, total, label)` is called as work advances.
    `is_cancelled()` is polled between chunks for cooperative cancellation.
    `partial(chars)` is called after each chunk with provisional cards (grouped
    candidates, no LLM merge yet) so the UI can render the cast as it reads.
    """
    cfg = CONFIG.extraction
    if cfg.max_chunks is not None:
        chunks = chunks[: cfg.max_chunks]

    total = len(chunks)
    all_mentions: list[CharacterMention] = []

    for idx, chunk in enumerate(chunks, start=1):
        if is_cancelled and is_cancelled():
            logger.info("Character extraction cancelled at chunk %d", idx)
            break
        if progress:
            progress(idx - 1, total, f"Reading chunk {idx} of {total}")
        try:
            all_mentions.extend(map_chunk(chunk))
        except ollama_service.OllamaError as err:
            logger.error("Chunk %d failed, skipping: %s", idx, err)
        if progress:
            progress(idx, total, f"Read chunk {idx} of {total}")
        if partial and all_mentions:
            prov = code_merge(group_mentions(all_mentions))
            build_descriptions(prov)
            partial(assign_roles(speaking_only(prov)))

    if progress:
        progress(total, total, "Merging character registry")

    grouped = group_mentions(all_mentions)
    if not grouped:
        return []

    # Deterministic merge + descriptions (no LLM reduce — both models echoed the
    # prompt / hallucinated counts there). Code merge folds "Jeff" into
    # "Jeff Baker"; descriptions are built from the collected traits.
    merged = code_merge(grouped)
    build_descriptions(merged)
    final = assign_roles(speaking_only(merged))

    if project is not None:
        from app.services import project_service

        project_service.save_analysis(project, all_mentions, grouped, final)

    return final


# --- per-character portrait prompts (LLM-written) ----------------------------


def write_portrait_prompts(
    characters: list[Character],
    bible: StyleBible,
    progress: ProgressCb | None = None,
) -> list[Character]:
    """Have the LLM write a distinct, book-fitting portrait prompt per character
    (varied clothing/background, ordinary look, name-free). Narrator skipped."""
    targets = [c for c in characters if c.role_importance != RoleImportance.narrator]
    total = len(targets)
    for i, c in enumerate(targets, start=1):
        if progress:
            progress(i, total, f"Writing portrait prompt {i}/{total}")
        who = f"{c.age_band.value.replace('_', ' ')} {c.gender_guess.value}"
        prompt = prompts.render(
            "portrait_prompt_prompt",
            art_style=bible.art_style,
            aesthetics=bible.aesthetics,
            lighting=bible.lighting,
            palette=", ".join(bible.color_palette),
            setting=bible.setting,
            casting=bible.casting,
            backgrounds=" | ".join(bible.background_variants or [bible.background]),
            wardrobes=" | ".join(bible.wardrobe_variants or [bible.wardrobe]),
            who=who,
            appearance=c.appearance_description or ", ".join(c.appearance_traits),
            clothing=", ".join(
                t for t in c.appearance_traits
                if any(k in t.lower() for k in ("coat", "shirt", "dress", "jacket",
                       "hat", "suit", "mantel", "kleid", "jacke", "hemd", "anzug"))
            ) or "none specified",
        )
        try:
            res = ollama_service.generate_json(prompt, PortraitPromptResult)
            if res.prompt:
                c.portrait_prompt = res.prompt
        except ollama_service.OllamaError as err:
            logger.warning("Portrait prompt failed for %s: %s", c.display_name, err)
    return characters


# --- web enrichment (opt-in) -------------------------------------------------

_NO_WEB_ROLES = {RoleImportance.narrator, RoleImportance.crowd}


def enrich_with_web(
    characters: list[Character],
    book_title: str,
    progress: ProgressCb | None = None,
) -> list[Character]:
    """Refine looks/voice of the top characters from web search (spoiler-safe).

    Only the most prominent characters are enriched (narrator/crowd skipped).
    Web text is passed through a strict spoiler firewall in the prompt.
    """
    targets = [c for c in characters if c.role_importance not in _NO_WEB_ROLES]
    targets = targets[: CONFIG.extraction.web_enrich_top_n]
    total = len(targets)
    for i, c in enumerate(targets, start=1):
        if progress:
            progress(i, total, f"Researching {c.display_name} ({i}/{total})")
        ctx = research_service.character_context(book_title, c.display_name)
        if not ctx:
            continue
        known = {
            "appearance_description": c.appearance_description,
            "voice_hint": c.voice_hint,
            "appearance_traits": c.appearance_traits,
            "vocal_traits": c.vocal_traits,
        }
        prompt = prompts.render(
            "character_web_enrich_prompt",
            character_name=c.display_name,
            known_json=json.dumps(known, ensure_ascii=False),
            web_context=ctx[:2500],
        )
        try:
            enr: WebEnrichment = ollama_service.generate_json(prompt, WebEnrichment)
        except ollama_service.OllamaError as err:
            logger.warning("Web enrich failed for %s: %s", c.display_name, err)
            continue
        if enr.appearance_description:
            c.appearance_description = enr.appearance_description
        if enr.voice_hint:
            c.voice_hint = enr.voice_hint
        c.appearance_traits = sorted(set(c.appearance_traits) | set(enr.appearance_traits))
        c.vocal_traits = sorted(set(c.vocal_traits) | set(enr.vocal_traits))
    return characters
