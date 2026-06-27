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


# OmniVoice supports NO emotion/style/prosody — only a fixed set of inline
# paralinguistic tags. We map the few Nonverbals that have an equivalent and
# drop everything else (emotion, style, prosody, unsupported SFX).
_OMNI_TAGS = {
    Nonverbal.laughter: "[laughter]",
    Nonverbal.sigh: "[sigh]",
}


def build_omnivoice_text(text: str, delivery: Delivery | None = None) -> str:
    """Plain text plus only OmniVoice's supported inline tags (no emotions)."""
    body = text.strip()
    if delivery is None:
        return body
    tags = "".join(_OMNI_TAGS[n] + " " for n in delivery.nonverbal if n in _OMNI_TAGS)
    return f"{tags}{body}"


# Map a clone workflow (by its node class_types) to a tag style. Cached so the
# template isn't re-read per line. "omnivoice" -> no emotions; else Higgs.
_STYLE_CACHE: dict[str, str] = {}


def tag_style_for_workflow(workflow_name: str) -> str:
    if workflow_name in _STYLE_CACHE:
        return _STYLE_CACHE[workflow_name]
    style = "higgs"
    try:
        from app.services import comfy_service
        graph = comfy_service._load_template(workflow_name)
        ctypes = " ".join(n.get("class_type", "") for n in graph.values()).lower()
        if "omnivoice" in ctypes:
            style = "omnivoice"
    except Exception:  # noqa: BLE001
        if "omni" in workflow_name.lower():
            style = "omnivoice"
    _STYLE_CACHE[workflow_name] = style
    return style


def build_text(text: str, delivery: Delivery | None, style: str = "higgs") -> str:
    """Build engine-appropriate control text for a line."""
    if style == "omnivoice":
        return build_omnivoice_text(text, delivery)
    return build_higgs_text(text, delivery)


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
