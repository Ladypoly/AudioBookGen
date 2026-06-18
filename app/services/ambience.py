"""Derive an ambience bed prompt for a chapter from its setting.

Deterministic keyword scan over the chapter title + opening prose. A later LLM
pass could pick per-scene ambience, but one bed per chapter is a solid start.
"""

from __future__ import annotations

from app.schemas.script import Chapter

# (keywords) -> (English Stable-Audio ambience description). First match wins;
# order from most specific to generic.
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("flugzeug", "fliegerhorst", "luftwaffe", "rollbahn", "hangar", "jet"),
     "Outdoor airfield on a sunny day, distant jet engines and turboprops, a large crowd murmuring, light wind, occasional public-address announcements, wide stereo"),
    (("party", "feier", "tanz", "diskothek", "dröhnte die musik", "fete"),
     "Lively indoor house party, muffled energetic dance music through walls, overlapping crowd chatter and laughter, clinking glasses, warm reverberant room"),
    (("pool", "schwimm", "bikini", "strand", "jetski", "wasser", "meer"),
     "Sunny outdoor poolside, gentle water splashes and ripples, relaxed distant chatter, birdsong, soft warm breeze"),
    (("büro", "schreibtisch", "konferenz", "meeting", "vorstand", "bank"),
     "Quiet modern office interior, soft ventilation hum, faint keyboard typing, distant muffled phone and voices, calm indoor ambience"),
    (("klinik", "krankenhaus", "arzt", "pflegeheim", "behandlung", "labor"),
     "Quiet clinical interior, faint medical monitor beeps, soft ventilation drone, distant footsteps on hard floor, sterile calm ambience"),
    (("schule", "klassenzimmer", "oakham", "unterricht", "direktor"),
     "Quiet school interior, faint distant pupils and corridors, soft room tone, occasional muffled bell, calm reverberant hallway"),
    (("auto", "wagen", "fahrt", "straße", "verkehr", "chauffeur"),
     "Car interior while driving, steady low engine hum, smooth tyre road noise, faint wind, muffled enclosed cabin"),
    (("regen", "sturm", "gewitter", "unwetter"),
     "Steady rain on windows and rooftops, distant rolling thunder, gusting wind, cosy muffled indoor perspective"),
    (("küche", "essen", "restaurant", "kaffee", "mittagessen"),
     "Cosy kitchen and dining ambience, faint clatter of cutlery and crockery, soft bubbling, low distant chatter, warm domestic room tone"),
    (("nacht", "dunkel", "garten", "draußen", "abend"),
     "Quiet night outdoors, soft crickets and insects, gentle breeze through leaves, very distant traffic, calm open-air ambience"),
]

_DEFAULT = ("Quiet domestic room tone, subtle indoor ambience, soft distant "
            "household sounds, gentle reverberant space")

# Generate a short clip and loop it seamlessly under the whole chapter.
GEN_SECONDS = 30.0


def ambience_for_chapter(chapter: Chapter) -> tuple[str, float]:
    """Return (Stable-Audio prompt, generation seconds) for this chapter."""
    hay = f"{chapter.title}\n{chapter.text[:1500]}".lower()
    for keys, prompt in _RULES:
        if any(k in hay for k in keys):
            return prompt, GEN_SECONDS
    return _DEFAULT, GEN_SECONDS
