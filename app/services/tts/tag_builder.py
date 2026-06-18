"""TagBuilder: Delivery metadata -> Higgs Audio v3 control-token text.

The ONLY place that knows Higgs `<|...|>` syntax (PLAN Appendix A.1). Delivery
turn-level tokens (emotion, style, prosody speed/pitch, expressive) go at the
START of the turn; pauses and nonverbal SFX go inline. Onomatopoeia is paired
with each SFX token as the model requires.
"""

from __future__ import annotations

from app.schemas.voice import Delivery, Nonverbal, Prosody

# SFX tokens must be followed by matching onomatopoeia.
_ONOMATOPOEIA = {
    Nonverbal.cough: "Ahem",
    Nonverbal.laughter: "Haha",
    Nonverbal.crying: "Sob",
    Nonverbal.screaming: "Aaah",
    Nonverbal.burping: "Urp",
    Nonverbal.humming: "Hmm",
    Nonverbal.sigh: "Uh",
    Nonverbal.sniff: "Sniff",
    Nonverbal.sneeze: "Achoo",
}

# Prosody tokens that shape the whole turn -> emitted at the start.
_TURN_PROSODY = {
    Prosody.speed_very_slow, Prosody.speed_slow, Prosody.speed_fast,
    Prosody.speed_very_fast, Prosody.pitch_low, Prosody.pitch_high,
    Prosody.expressive_high, Prosody.expressive_low,
}


def _tok(category: str, value: str) -> str:
    return f"<|{category}:{value}|>"


def build_higgs_text(text: str, delivery: Delivery | None = None) -> str:
    """Return the line text with Higgs control tokens applied."""
    if delivery is None:
        return text

    lead: list[str] = []
    if delivery.emotion is not None:
        lead.append(_tok("emotion", delivery.emotion.value))
    if delivery.style is not None:
        lead.append(_tok("style", delivery.style.value))
    for p in delivery.prosody:
        if p in _TURN_PROSODY:
            lead.append(_tok("prosody", p.value))

    body = text.strip()

    # Inline pauses (pause / long_pause) appended after the line as a beat.
    tail: list[str] = []
    for p in delivery.prosody:
        if p in (Prosody.pause, Prosody.long_pause):
            tail.append(_tok("prosody", p.value))

    # Nonverbal SFX prepended inline with onomatopoeia.
    sfx = "".join(
        _tok("sfx", n.value) + _ONOMATOPOEIA.get(n, "") + " " for n in delivery.nonverbal
    )

    return f"{''.join(lead)}{sfx}{body}{''.join(tail)}"
