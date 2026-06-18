"""Pick a short intro music cue per chapter from its mood.

Deterministic keyword scan over the chapter title + opening prose maps to one of
a few instrumental moods (Stable Audio music prompts). A short cue is prepended
to the chapter as an intro sting.
"""

from __future__ import annotations

from app.core.config import CONFIG
from app.schemas.script import Chapter

# (keywords) -> instrumental Stable-Audio music prompt (no vocals).
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("party", "feier", "tanz", "diskothek", "fete", "willkommen"),
     "Upbeat electronic pop intro with bright synth plucks, punchy drums and warm bass, energetic and youthful. BPM: 120"),
    (("verschwörung", "polizei", "europol", "bedroht", "gefahr", "entführ", "jagd",
      "aufruhr", "demonstr", "flucht", "angst"),
     "Tense cinematic intro with pulsing low synth bass, ticking percussion and high sustained strings, suspenseful and dark. BPM: 100"),
    (("liebe", "tante", "erinnerung", "familie", "abschied", "traum", "still"),
     "Warm reflective intro with soft felt piano, gentle string pad and light vibraphone, tender and nostalgic. BPM: 70"),
    (("büro", "finanz", "vorstand", "konferenz", "offiziell", "besuch", "nachrichten",
      "presse", "rede"),
     "Sleek corporate intro with clean electric piano, subtle pad and soft mallet pulse, composed and modern. BPM: 95"),
    (("klinik", "labor", "behandlung", "verjüng", "gene", "wissenschaft"),
     "Cool futuristic intro with airy synth pads, glassy bell tones and a slow analog arpeggio, clinical and hopeful. BPM: 90"),
]

_DEFAULT = ("Gentle neutral storybook intro with soft piano, light strings and a "
            "warm pad, calm and inviting. BPM: 80")


def music_for_chapter(chapter: Chapter) -> tuple[str, float]:
    """Return (Stable-Audio music prompt, seconds) for this chapter's intro.

    The title is the strongest mood signal, so match it first; only fall back to
    scanning the opening prose if the title is inconclusive."""
    title = chapter.title.lower()
    for keys, prompt in _RULES:
        if any(k in title for k in keys):
            return prompt, CONFIG.tts.music_seconds
    body = chapter.text[:1200].lower()
    for keys, prompt in _RULES:
        if any(k in body for k in keys):
            return prompt, CONFIG.tts.music_seconds
    return _DEFAULT, CONFIG.tts.music_seconds
