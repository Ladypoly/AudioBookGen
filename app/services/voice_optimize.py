"""Optimize a voice sample: (optional) separate vocals from background, denoise,
enhance, then trim silence + normalise.

Each AI step is optional and guarded — if the library isn't installed the step
is skipped and noted, so the module works out of the box (trim + normalise) and
gets better as you `pip install` the optional models:

    pip install deepfilternet      # denoise (tiny, CPU, real-time) — recommended
    pip install demucs             # separate vocals from music/ambience
    pip install voicefixer         # restore + 44.1 kHz super-resolution (Windows-ok)
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
import tempfile
from pathlib import Path

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

OPTIMIZED_DIR = PROJECT_ROOT / "optimized"


def available() -> dict[str, bool]:
    """Which optional optimizers are installed."""
    return {
        "separate (demucs)": importlib.util.find_spec("demucs") is not None,
        "denoise (deepfilternet)": importlib.util.find_spec("df") is not None,
        "enhance (voicefixer)": importlib.util.find_spec("voicefixer") is not None,
    }


def _separate_vocals(src: Path, work: Path) -> Path | None:
    """Demucs: isolate the vocal stem from music/ambience."""
    if importlib.util.find_spec("demucs") is None:
        return None
    import subprocess
    import sys
    out = work / "demucs"
    cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", str(out), str(src)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.warning("demucs failed: %s", res.stderr[-300:])
        return None
    found = list(out.glob(f"*/{src.stem}/vocals.*"))
    return found[0] if found else None


def _denoise(src: Path, work: Path) -> Path | None:
    """DeepFilterNet: noise + reverb suppression (tiny, CPU, fast)."""
    if importlib.util.find_spec("df") is None:
        return None
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio
        model, df_state, _ = init_df()
        audio, _ = load_audio(str(src), sr=df_state.sr())
        enhanced = enhance(model, df_state, audio)
        out = work / "denoised.wav"
        save_audio(str(out), enhanced, df_state.sr())
        return out
    except Exception:  # noqa: BLE001
        logger.exception("deepfilternet failed")
        return None


def _enhance(src: Path, work: Path) -> Path | None:
    """VoiceFixer: speech restoration + 44.1 kHz super-resolution (no DeepSpeed,
    Windows-friendly). Downloads model weights on first use."""
    if importlib.util.find_spec("voicefixer") is None:
        return None
    try:
        import torch
        from voicefixer import VoiceFixer
        vf = VoiceFixer()
        out = work / "enhanced.wav"
        vf.restore(input=str(src), output=str(out),
                   cuda=torch.cuda.is_available(), mode=0)
        return out if out.exists() else None
    except Exception:  # noqa: BLE001
        logger.exception("voicefixer failed")
        return None


def _loudnorm(src: Path, out: Path) -> bool:
    """Loudness-normalise to a fixed LUFS target so every voice is equally loud
    (ffmpeg loudnorm + true-peak limit). Returns False if ffmpeg is unavailable."""
    import subprocess
    from app.core.config import CONFIG
    if not shutil.which("ffmpeg"):
        return False
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"loudnorm=I={CONFIG.tts.voice_norm_lufs}:TP={CONFIG.tts.voice_norm_tp}:LRA=7",
        "-ar", "48000", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and out.exists()


def _trim_normalize(src: Path, out: Path) -> None:
    from pydub import AudioSegment
    from pydub.effects import normalize
    from pydub.silence import detect_leading_silence
    seg = AudioSegment.from_file(src)
    lead = detect_leading_silence(seg, silence_threshold=-45.0, chunk_size=10)
    trail = detect_leading_silence(seg.reverse(), silence_threshold=-45.0, chunk_size=10)
    if lead + trail < len(seg):
        seg = seg[lead:len(seg) - trail]
    out.parent.mkdir(parents=True, exist_ok=True)

    # Loudness-normalise (LUFS) so all voices match; fall back to peak-normalise.
    tmp = out.with_name(out.stem + ".trim.wav")
    seg.export(tmp, format="wav")
    if not _loudnorm(tmp, out):
        normalize(seg).export(out, format="wav")
    tmp.unlink(missing_ok=True)


def optimize(in_path: str | Path, out_path: str | Path | None = None,
             separate: bool = False, denoise: bool = True,
             enhance: bool = False) -> dict:
    """Run the optimize pipeline. Returns {out, done, skipped}."""
    src = Path(in_path)
    if not src.exists():
        raise FileNotFoundError(src)
    out = Path(out_path) if out_path else OPTIMIZED_DIR / f"{src.stem}_optimized.wav"
    done: list[str] = []
    skipped: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        cur = src
        for flag, name, fn in (
            (separate, "separate", _separate_vocals),
            (denoise, "denoise", _denoise),
            (enhance, "enhance", _enhance),
        ):
            if not flag:
                continue
            res = fn(cur, work)
            if res is not None:
                cur = res
                done.append(name)
            else:
                skipped.append(name + " (not installed / failed)")
        _trim_normalize(cur, out)
        done.append("trim + normalize")

    return {"out": str(out), "done": done, "skipped": skipped}
