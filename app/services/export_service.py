"""Export assembled chapters as a single M4B audiobook with chapter marks."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _esc(s: str) -> str:
    """Escape ffmetadata special characters."""
    for ch in ("\\", "=", ";", "#", "\n"):
        s = s.replace(ch, "\\" + ch if ch != "\n" else " ")
    return s


def export_m4b(project, infos: list[dict], bitrate: str = "128k") -> Path:
    """Concatenate existing chapter mixes into one .m4b with chapter markers.

    `infos` is the chapter index (needs number/title/chapter_id). Chapters
    without rendered audio are skipped. Returns the output path."""
    from pydub import AudioSegment

    ordered = sorted(infos, key=lambda x: x["number"])
    entries: list[tuple[Path, dict, int, int]] = []
    skipped: list[str] = []
    cum = 0
    for info in ordered:
        p = project.chapter_audio_dir / f"{info['chapter_id']}.mp3"
        if not p.exists():
            continue
        try:                                   # skip corrupt/partial files
            dur = len(AudioSegment.from_file(p))
            if dur < 100 or p.stat().st_size < 2048:
                raise ValueError("too short / truncated")
        except Exception as err:  # noqa: BLE001
            logger.warning("Skipping unreadable chapter %s: %s", info["chapter_id"], err)
            skipped.append(info["chapter_id"])
            continue
        entries.append((p, info, cum, cum + dur))
        cum += dur
    if not entries:
        raise RuntimeError("No valid chapter audio to export.")
    if skipped:
        logger.warning("Export skipped %d chapters: %s", len(skipped), skipped)

    export_dir = project.root / "export"
    export_dir.mkdir(parents=True, exist_ok=True)

    concat = export_dir / "concat.txt"
    concat.write_text(
        "\n".join(f"file '{str(p).replace(chr(92), '/')}'" for p, *_ in entries),
        encoding="utf-8",
    )

    meta_lines = [";FFMETADATA1", f"title={_esc(project.title)}",
                  "artist=Book2AudioDrama", "genre=Audiobook"]
    for _p, info, start, end in entries:
        chap_title = _esc(f"{info['number']}. {info['title']}")
        meta_lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}",
                       f"END={end}", f"title={chap_title}"]
    meta = export_dir / "chapters.ffmeta"
    meta.write_text("\n".join(meta_lines), encoding="utf-8")

    out = export_dir / f"{project.root.name}.m4b"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(meta),
        "-map", "0:a", "-map_metadata", "1",
        "-c:a", "aac", "-b:a", bitrate,
        "-movflags", "+faststart",
        str(out),
    ]
    logger.info("Exporting M4B: %d chapters -> %s", len(entries), out)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-800:]}")
    return out
