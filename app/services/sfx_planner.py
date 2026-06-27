"""Discrete SFX detection + generation.

Scans NARRATION lines for described sound events and attaches SfxCues. SFX are
only ever attached to narration (never dialogue), so at mix time they sit under
the narrator or in a pause and never collide with a character's voice.
"""

from __future__ import annotations

import logging
import re

from app.schemas.script import Chapter, LineItem, LineType, SfxCue

logger = logging.getLogger(__name__)

# (trigger substrings, English Stable-Audio prompt, length_s, gain_db, placement)
# First match wins per concept; at most 2 cues per line. Phrases are matched in
# the lower-cased line text.
_RULES: list[tuple[tuple[str, ...], str, float, float, str]] = [
    (("tür ins schloss", "schlug die tür", "knallte die tür", "tür knallte",
      "warf die tür", "tür zuschlug", "schmiss die tür", "tür zugeschlagen"),
     "a heavy wooden door slamming shut, sharp impact with indoor reverb", 2.0, -5.0, "gap"),
    (("öffnete die tür", "tür aufging", "tür knarrte", "knarrte die tür",
      "tür ging auf", "tür schwang auf", "stieß die tür auf"),
     "an old wooden door creaking slowly open, indoor reverb", 3.0, -8.0, "over"),
    (("klopfte an die tür", "klopfen an der tür", "es klopfte an", "klopfte an der tür",
      "klopfte an"),
     "firm knuckles knocking on a wooden door", 2.0, -7.0, "over"),
    (("glas zerbrach", "glas zersplitterte", "zersplitterte", "glas zersprang",
      "glas zerschellte", "klirrend zu boden", "zersprang klirrend"),
     "glass shattering on a hard floor, sharp break and scattered shards", 2.0, -6.0, "gap"),
    (("telefon klingelte", "handy klingelte", "telefon läutete",
      "klingelte das telefon", "klingelte sein telefon", "das telefon klingelte"),
     "a phone ringing twice, indoor", 3.0, -8.0, "over"),
    (("schüsse", "ein schuss fiel", "schuss fiel", "der schuss", "abgefeuert",
      "drückte ab", "gewehrfeuer", "ein schuss krachte"),
     "a single gunshot with a sharp crack and echo", 2.0, -5.0, "gap"),
    (("explosion", "explodierte", "detonation", "flog in die luft"),
     "a large explosion, deep bass boom with debris", 3.0, -4.0, "gap"),
    (("sirene", "martinshorn", "polizeisirene"),
     "a distant emergency siren wailing", 4.0, -9.0, "over"),
    (("donnerte", "donnergrollen", "es donnerte", "grollte der donner", "ein gewitter"),
     "a low rolling thunder rumble in the distance", 4.0, -8.0, "over"),
    (("applaus", "applaudier", "beifall", "klatschten beifall",
      "klatschten in die hände", "klatschten begeistert"),
     "a crowd applauding and clapping", 4.0, -9.0, "over"),
    (("motor sprang an", "motor heulte", "startete den motor", "motor aufheulen",
      "ließ den motor an", "gab gas"),
     "a car engine starting and revving, exterior", 3.0, -9.0, "over"),
    (("bremsen quietsch", "reifen quietsch", "quietschten die reifen"),
     "car tyres screeching on asphalt", 2.0, -7.0, "gap"),
    (("glocke läutete", "glocken läuteten", "läutete die glocke", "kirchenglocke"),
     "a church bell tolling slowly", 3.0, -8.0, "over"),
    (("hörte schritte", "schritte näher", "fußschritte", "schritte auf",
      "schritte hallten", "schnelle schritte", "leise schritte", "schritte im flur",
      "näherten sich schritte"),
     "slow footsteps on a hard floor, close perspective", 4.0, -11.0, "over"),
    (("hupte", "autohupe", "drückte auf die hupe"),
     "a short car horn honk", 1.5, -8.0, "gap"),
    (("schrie auf", "gellender schrei", "schriller schrei", "stieß einen schrei"),
     "a sudden human scream, short", 1.5, -8.0, "gap"),
    # --- everyday radio-drama foley (more density) ----------------------------
    (("schenkte ein", "goss", "eingoss", "schenkte sich", "schlürfte", "nippte",
      "schenkte kaffee", "schenkte tee", "schenkte wein"),
     "pouring a hot drink into a cup, gentle liquid and soft ceramic", 3.0, -9.0, "over"),
    (("geschirr", "teller klapperten", "klapperten teller", "besteck", "klirrten gläser",
      "stießen die gläser", "stießen mit den gläsern"),
     "clinking plates, glasses and cutlery in a kitchen", 3.0, -9.0, "over"),
    (("stuhl rückte", "rückte den stuhl", "schob den stuhl", "stuhl scharrte",
      "schob seinen stuhl", "rückte seinen stuhl"),
     "a wooden chair scraping back on a hard floor", 2.0, -8.0, "gap"),
    (("wasser rauschte", "wasserhahn", "dusche", "plätscherte", "ließ wasser"),
     "running tap water, gentle splashing", 3.0, -10.0, "over"),
    (("regen prasselte", "regen trommelte", "prasselte der regen", "regen klatschte"),
     "rain pattering steadily on a window", 4.0, -10.0, "over"),
    (("wind heulte", "wind pfiff", "wind fauchte", "böen", "sturm heulte"),
     "wind gusting and whistling outdoors", 4.0, -10.0, "over"),
    (("stimmengewirr", "gemurmel", "raunen ging", "viele stimmen", "stimmen schwirrten"),
     "a crowd of people murmuring indoors", 4.0, -11.0, "over"),
    (("gelächter", "alle lachten", "lachten laut", "brachen in lachen", "prustete los"),
     "a group of people laughing together", 3.0, -10.0, "over"),
    (("tippte", "tastatur", "tippen auf", "hämmerte auf die tasten"),
     "fingers typing quickly on a keyboard", 3.0, -10.0, "over"),
    (("summte das handy", "vibrierte", "handy summte", "piepte kurz", "piepton"),
     "a phone buzzing with a short notification", 1.5, -9.0, "over"),
    (("fuhr vorbei", "rauschte vorbei", "vorbeifahrende", "raste vorbei", "brauste vorbei"),
     "a car passing by at speed with a doppler whoosh", 3.0, -9.0, "over"),
    (("vögel zwitscherten", "vogelgezwitscher", "zwitscherten", "amsel", "möwen"),
     "birds chirping outdoors on a calm day", 4.0, -11.0, "over"),
    (("uhr tickte", "ticken der uhr", "tickte", "pendeluhr"),
     "an old clock ticking steadily", 3.0, -12.0, "over"),
    (("feuer knisterte", "kamin", "flammen knisterten", "knisterte das feuer", "lagerfeuer"),
     "a wood fire crackling softly", 4.0, -10.0, "over"),
    (("schlüssel", "schloss klickte", "schloss auf", "drehte den schlüssel", "schlüsselbund"),
     "keys jingling and a lock clicking open", 2.0, -8.0, "over"),
    (("korken", "entkorkte", "flasche öffnete", "öffnete die flasche", "knallte der korken"),
     "a cork popping out of a bottle", 1.5, -7.0, "gap"),
    (("feuerzeug", "zündete sich eine", "anzündete", "streichholz", "rauchte"),
     "a lighter flicking on and a cigarette lit", 2.0, -10.0, "over"),
    (("brandung", "meer rauschte", "wellen schlugen", "wellen klatschten",
      "meeresrauschen", "rauschen des meeres"),
     "ocean waves rolling onto a shore", 4.0, -11.0, "over"),
    (("aufzug", "fahrstuhl"),
     "an elevator chime and doors sliding open", 2.0, -9.0, "gap"),
]


# Compile each rule to a whole-word regex so e.g. "schüsse" does NOT fire on
# "Schüsseln"/"Ausschüssen" and "donnerte" not on "Donnerstag".
_COMPILED = [
    (re.compile(r"\b(?:" + "|".join(re.escape(t) for t in triggers) + r")\b", re.I),
     prompt, length, gain, placement)
    for triggers, prompt, length, gain, placement in _RULES
]


# Density -> (max cues per line, max cues per chapter; 0 chapter cap = no limit).
_DENSITY = {
    "off": (0, 0),
    "sparse": (1, 6),
    "normal": (2, 0),
    "rich": (3, 0),
}


def annotate(lines: list[LineItem]) -> None:
    """Attach keyword-detected SfxCues to narration lines in place.

    This is the deterministic LOCAL fallback. Lines that already carry cues
    (e.g. context-specific ones written by a chapter agent) are left untouched.
    How many cues are placed is governed by CONFIG.tts.sfx_density."""
    from app.core.config import CONFIG
    per_line, chap_cap = _DENSITY.get(CONFIG.tts.sfx_density, (2, 0))
    total = 0
    for line in lines:
        if line.sfx:                         # agent/dynamic cues — keep them
            continue
        if line.type is not LineType.narration or per_line == 0 or (
                chap_cap and total >= chap_cap):
            line.sfx = []
            continue
        cues: list[SfxCue] = []
        for rx, prompt, length, gain, placement in _COMPILED:
            if rx.search(line.text):
                cues.append(SfxCue(prompt=prompt, length_s=length,
                                   gain_db=gain, placement=placement))
                total += 1
                if len(cues) >= per_line or (chap_cap and total >= chap_cap):
                    break
        line.sfx = cues


def cues_for(chapter: Chapter) -> list[SfxCue]:
    """All unique cues in a chapter (annotate first)."""
    seen, out = set(), []
    for line in chapter.lines:
        for cue in line.sfx:
            if cue.custom:                  # user-dropped clip — never generated
                continue
            key = (cue.prompt, cue.length_s)
            if key not in seen:
                seen.add(key)
                out.append(cue)
    return out


def generate_chapter_sfx(project, chapter: Chapter, force: bool = False) -> int:
    """Generate missing SFX clips for the chapter (audio stage must be up).
    `force` re-generates even existing clips. Returns how many were generated."""
    from app.services import sound_service

    made = 0
    for cue in cues_for(chapter):
        out = project.sfx_clip_path(cue)
        if out.exists() and not force:
            continue
        try:
            sound_service.generate(cue.prompt, cue.length_s, out, kind="sfx")
            made += 1
        except Exception:  # noqa: BLE001
            logger.exception("SFX generation failed: %s", cue.prompt)
    return made
