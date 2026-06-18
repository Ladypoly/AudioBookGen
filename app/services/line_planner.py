"""Line planning: chapter prose -> ordered LineItems (narration / dialogue).

Deterministic first pass:
  - German quotes (»…« or „…") become dialogue lines, the prose between them
    narration lines (spoken by the narrator).
  - Each dialogue's speaker is attributed from a nearby "sagte <Name>" pattern
    and resolved to a registry character; unresolved dialogue falls back to the
    narrator so a chapter is always fully renderable.

A later LLM pass can refine speaker attribution and add expressive delivery.
"""

from __future__ import annotations

import logging
import re

from app.schemas.characters import Character
from app.schemas.script import Chapter, LineItem, LineType
from app.schemas.voice import Delivery, Emotion, Nonverbal, Prosody, Style

logger = logging.getLogger(__name__)

NARRATOR_ID = "erzaehler"

# Attribution verb (stem) -> delivery hints, matched against words near a quote.
_VERB_DELIVERY: dict[str, tuple] = {
    "schrie": (Emotion.anger, Style.shouting, None, None),
    "brüllte": (Emotion.anger, Style.shouting, None, None),
    "kreischte": (Emotion.fear, Style.shouting, None, None),
    "rief": (None, None, Prosody.expressive_high, None),
    "flüsterte": (None, Style.whispering, Prosody.speed_slow, None),
    "raunte": (None, Style.whispering, None, None),
    "murmelte": (None, Style.whispering, None, None),
    "lachte": (Emotion.amusement, None, None, Nonverbal.laughter),
    "kicherte": (Emotion.amusement, None, None, None),
    "seufzte": (Emotion.sadness, None, None, Nonverbal.sigh),
    "stammelte": (Emotion.helplessness, None, Prosody.speed_slow, None),
    "stotterte": (Emotion.fear, None, Prosody.speed_slow, None),
    "schluchzte": (Emotion.sadness, None, None, Nonverbal.crying),
    "jammerte": (Emotion.helplessness, None, None, None),
    "knurrte": (Emotion.bitterness, None, Prosody.pitch_low, None),
    "brummte": (Emotion.bitterness, None, Prosody.pitch_low, None),
    "fauchte": (Emotion.anger, None, None, None),
    "zischte": (Emotion.anger, Style.whispering, None, None),
    "befahl": (Emotion.determination, None, None, None),
    "verlangte": (Emotion.determination, None, None, None),
}

# Emotional adverbs/adjectives near a quote -> emotion.
_ADVERB_EMOTION: dict[str, Emotion] = {
    "wütend": Emotion.anger, "zornig": Emotion.anger, "aufgebracht": Emotion.anger,
    "verärgert": Emotion.anger, "gereizt": Emotion.anger,
    "traurig": Emotion.sadness, "betrübt": Emotion.sadness, "niedergeschlagen": Emotion.sadness,
    "ängstlich": Emotion.fear, "erschrocken": Emotion.fear, "panisch": Emotion.fear,
    "nervös": Emotion.fear, "unsicher": Emotion.helplessness,
    "fröhlich": Emotion.elation, "heiter": Emotion.amusement, "vergnügt": Emotion.amusement,
    "begeistert": Emotion.enthusiasm, "aufgeregt": Emotion.enthusiasm,
    "überrascht": Emotion.surprise, "verblüfft": Emotion.surprise, "erstaunt": Emotion.surprise,
    "verächtlich": Emotion.bitterness, "spöttisch": Emotion.bitterness, "höhnisch": Emotion.disgust,
    "liebevoll": Emotion.affection, "zärtlich": Emotion.affection, "sanft": Emotion.affection,
    "bestimmt": Emotion.determination, "entschlossen": Emotion.determination,
    "ruhig": Emotion.contentment, "gelassen": Emotion.contentment,
    "verzweifelt": Emotion.helplessness, "kläglich": Emotion.helplessness,
    "bitter": Emotion.bitterness, "beschämt": Emotion.shame, "verlegen": Emotion.shame,
}


def infer_delivery(quote: str, context: str) -> Delivery:
    """Derive expressive Higgs delivery from the attribution verb, nearby
    emotional adverbs, and the quote's own punctuation."""
    d = Delivery()
    low = context.lower()
    for verb, (emo, sty, pro, nv) in _VERB_DELIVERY.items():
        if verb in low:
            if emo:
                d.emotion = emo
            if sty:
                d.style = sty
            if pro and pro not in d.prosody:
                d.prosody.append(pro)
            if nv and nv not in d.nonverbal:
                d.nonverbal.append(nv)
            break
    if not d.emotion:
        for adv, emo in _ADVERB_EMOTION.items():
            if adv in low:
                d.emotion = emo
                break
    q = quote.strip()
    if q.endswith("!") and Prosody.expressive_high not in d.prosody:
        d.prosody.append(Prosody.expressive_high)
    if ("..." in q or "…" in q) and Prosody.pause not in d.prosody:
        d.prosody.append(Prosody.pause)
    return d

# Quote spans: guillemets »..« and German low-high „..“/”.
_QUOTE = re.compile(
    "»([^»«]+)«|„([^„“”]+)[“”]"
)

# Speech verbs used for attribution + speech/emphasis classification.
_VERBS = (
    "sagte", "fragte", "erwiderte", "rief", "antwortete", "meinte", "brummte",
    "flüsterte", "murmelte", "stammelte", "schrie", "entgegnete", "erklärte",
    "verlangte", "hakte", "stieß", "kicherte", "lachte", "seufzte", "erkundigte",
    "knurrte", "raunte", "fauchte", "zischte", "befahl", "schluchzte", "jammerte",
    "wiederholte", "fuhr fort", "begann", "protestierte", "widersprach", "bat",
    "kreischte", "brüllte", "stotterte", "rief aus", "gab zu", "gestand",
)
_VERB_RE = "|".join(v.split()[0] for v in _VERBS)
# Optional connectors between the verb and the name: "sagte Jeff", "erkundigte
# sich Sue", "fragte die kleine Tante", "rief der Junge".
_CONN = r"(?:sich\s+)?(?:wieder\s+)?(?:der|die|das|den|dem|sein|seine|seinen|ihre?|ihren|ein|eine|kleine|alte|junge)?\s*"
_ATTR_AFTER = re.compile(rf"\b(?:{_VERB_RE})\b\s+{_CONN}([A-ZÄÖÜ][\wäöüß]+)")
# "Jeff sagte" / "Sue fragte misstrauisch" → leading name before the verb.
_ATTR_BEFORE = re.compile(rf"([A-ZÄÖÜ][\wäöüß]+)\s+(?:\w+\s+)?(?:{_VERB_RE})\b")
# A speech verb anywhere near a quote (for speech-vs-emphasis classification).
_VERB_NEAR = re.compile(rf"\b(?:{_VERB_RE})\b")


def _name_index(characters: list[Character]) -> dict[str, str]:
    """Map lower-cased names + aliases + first names -> character_id."""
    idx: dict[str, str] = {}
    for c in characters:
        names = [c.display_name, *c.aliases]
        for n in names:
            idx[n.lower()] = c.character_id
            first = n.split()[0].lower()
            idx.setdefault(first, c.character_id)
    return idx


_PRON_VERB = re.compile(rf"\b(?:{_VERB_RE})\b\s+(er|sie)\b")
_NAME_TOKEN = re.compile(r"[A-ZÄÖÜ][\wäöüß]+")


def _gender_index(characters: list[Character]) -> dict[str, str]:
    return {c.character_id: c.gender_guess.value for c in characters}


def _attribute(context: str, names: dict[str, str]) -> str | None:
    for rx in (_ATTR_AFTER, _ATTR_BEFORE):
        for m in rx.finditer(context):
            cand = m.group(1).lower()
            if cand in names:
                return names[cand]
    return None


def _resolve_pronoun(before: str, after: str, names: dict[str, str],
                     genders: dict[str, str]) -> str | None:
    """Resolve "..., sagte er/sie" to the nearest preceding character of the
    matching gender (handles pronoun-attributed dialogue)."""
    m = _PRON_VERB.search(after) or _PRON_VERB.search(before[-60:])
    if not m:
        return None
    want = "male" if m.group(1) == "er" else "female"
    best = None
    for nm in _NAME_TOKEN.finditer(before[-260:]):  # last wins = nearest
        cid = names.get(nm.group(0).lower())
        if cid and genders.get(cid) == want:
            best = cid
    return best


def _is_speech(inner: str, ctx: str) -> bool:
    """Tell a spoken quote from an emphasis quote (»nie versiegender Hahn«).

    Speech either ends in sentence punctuation or sits next to a speech verb;
    a short noun phrase with neither is emphasis and stays inside narration."""
    s = inner.strip()
    if not s:
        return False
    if s[-1] in ".!?…":
        return True
    if _VERB_NEAR.search(ctx):
        return True
    # Long quotes without end punctuation are still most likely speech.
    return len(s) > 60


# --- sentence segmentation ---------------------------------------------------
# So Higgs renders one coherent unit at a time (no mid-sentence chunk seams):
# merge short sentences up to TARGET, split over-long ones at commas.
_TARGET = 240
_MAX = 320
_ABBREV = re.compile(r"(?:\b(?:Dr|Mr|Mrs|Prof|Nr|St|ca|usw|bzw|z|d|u|etc)\.|\b[A-ZÄÖÜ]\.)$")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[»„\"A-ZÄÖÜ0-9])")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:–—])\s+")


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out: list[str] = []
    for part in _SENT_SPLIT.split(text):
        part = part.strip()
        if not part:
            continue
        # rejoin false splits after abbreviations ("Dr." + "Friland")
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _split_long(s: str) -> list[str]:
    parts = _CLAUSE_SPLIT.split(s)
    units, buf = [], ""
    for p in parts:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= _MAX:
            buf = f"{buf} {p}"
        else:
            units.append(buf)
            buf = p
    if buf:
        units.append(buf)
    return units


def to_units(text: str) -> list[str]:
    """Split text into render units: combine short sentences, split long ones."""
    units, buf = [], ""
    for s in _sentences(text):
        if len(s) > _MAX:
            if buf:
                units.append(buf)
                buf = ""
            units.extend(_split_long(s))
        elif not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= _TARGET:
            buf = f"{buf} {s}"
        else:
            units.append(buf)
            buf = s
    if buf:
        units.append(buf)
    return units


def delivery_from_agent(text: str, emotion=None, style=None,
                        prosody=None, nonverbal=None) -> Delivery:
    """Build a Delivery from an agent's emotion/style hints (validated against
    the Higgs vocab), plus punctuation cues."""
    d = Delivery()
    if emotion:
        try:
            d.emotion = Emotion(emotion)
        except ValueError:
            pass
    if style:
        try:
            d.style = Style(style)
        except ValueError:
            pass
    for p in prosody or []:
        try:
            d.prosody.append(Prosody(p))
        except ValueError:
            pass
    for nv in nonverbal or []:
        try:
            d.nonverbal.append(Nonverbal(nv))
        except ValueError:
            pass
    q = text.strip()
    if q.endswith("!") and Prosody.expressive_high not in d.prosody:
        d.prosody.append(Prosody.expressive_high)
    if ("..." in q or "…" in q) and Prosody.pause not in d.prosody:
        d.prosody.append(Prosody.pause)
    return d


def prepend_title(chapter) -> None:
    """Insert a narrator line announcing the chapter title at the very start
    (skipped for the front matter, number 0). Idempotent."""
    if chapter.number <= 0:
        return
    intro_id = f"{chapter.chapter_id}_l0000"
    if chapter.lines and chapter.lines[0].line_id == intro_id:
        return
    chapter.lines.insert(0, LineItem(
        line_id=intro_id, chapter_id=chapter.chapter_id, index=0,
        type=LineType.narration, speaker_id=NARRATOR_ID,
        text=f"Kapitel {chapter.number}: {chapter.title}.",
    ))


def test_slice(lines: list[LineItem], max_lines: int = 28,
               min_dialogues: int = 4, hard_cap: int = 55) -> list[LineItem]:
    """First-pages slice for quick tests: the opening lines, extended until a
    few dialogue lines are included (so narrator + speakers are both heard)."""
    out = list(lines[:max_lines])
    d = sum(1 for l in out if l.type == LineType.dialogue)
    i = len(out)
    while d < min_dialogues and i < min(len(lines), hard_cap):
        out.append(lines[i])
        if lines[i].type == LineType.dialogue:
            d += 1
        i += 1
    return out


def plan_chapter(chapter: Chapter, characters: list[Character]) -> list[LineItem]:
    names = _name_index(characters)
    genders = _gender_index(characters)
    text = chapter.text
    lines: list[LineItem] = []
    recent: list[str] = []      # last 2 distinct *named* speakers (exchange)
    prev_dialogue: str | None = None
    narr = ""        # accumulated narration (incl. inline emphasis quotes)
    n = 0

    def emit(kind: LineType, speaker: str, body: str, delivery: Delivery | None = None) -> None:
        nonlocal n
        for unit in to_units(body):
            n += 1
            lines.append(LineItem(
                line_id=f"{chapter.chapter_id}_l{n:04d}", chapter_id=chapter.chapter_id,
                index=n, type=kind, speaker_id=speaker, text=unit,
                delivery=delivery or Delivery(),
            ))

    def flush_narration() -> None:
        nonlocal narr
        if narr.strip():
            emit(LineType.narration, NARRATOR_ID, narr)
        narr = ""

    pos = 0
    for m in _QUOTE.finditer(text):
        inner = (m.group(1) or m.group(2) or "").strip()
        pre = text[pos:m.start()]
        ctx = text[max(0, m.start() - 60): m.end() + 60]
        pos = m.end()
        if _is_speech(inner, ctx):
            narr += pre
            flush_narration()
            speaker = _attribute(ctx, names)
            if speaker is None:  # "..., sagte er/sie" -> nearest matching name
                speaker = _resolve_pronoun(text[:m.start()], text[m.end():m.end() + 60],
                                           names, genders)
            if speaker is None:
                # No name at all: in an established two-person exchange alternate
                # to the other speaker; otherwise stay neutral (narrator).
                if len(recent) == 2 and prev_dialogue in recent:
                    speaker = recent[0] if prev_dialogue == recent[1] else recent[1]
                else:
                    speaker = NARRATOR_ID
            if speaker != NARRATOR_ID and (not recent or recent[-1] != speaker):
                recent.append(speaker)
                del recent[:-2]
            prev_dialogue = speaker
            emit(LineType.dialogue, speaker, inner, infer_delivery(inner, ctx))
        else:
            # emphasis quote → keep the words inline in the narration
            narr += f"{pre}{inner} "

    narr += text[pos:]
    flush_narration()
    return lines
