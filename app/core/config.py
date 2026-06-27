"""Application configuration.

Central, typed settings. For this first vertical slice the values are simple
defaults; later this is backed by SQLite settings + the Settings screen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Source-tree root. In a packaged build (PyInstaller) the bundled read-only
# assets (prompts/, workflows/) live next to the sidecar exe, and user-writable
# data (projects/, settings.json) lives in a per-user folder. Both are pointed
# at via env vars set by the Electron shell; unset, everything stays relative to
# the source tree (the dev / PySide6 behaviour is unchanged).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Read-only bundled assets (prompts, workflows).
ASSET_ROOT = Path(os.environ["ABG_ASSET_ROOT"]) if os.environ.get("ABG_ASSET_ROOT") else PROJECT_ROOT
# User-writable data (projects, settings).
DATA_ROOT = Path(os.environ["ABG_DATA_ROOT"]) if os.environ.get("ABG_DATA_ROOT") else PROJECT_ROOT

PROMPTS_DIR = ASSET_ROOT / "prompts"


@dataclass
class OllamaConfig:
    """LLM backend settings. `backend` selects local Ollama or any
    OpenAI-compatible HTTP API (OpenRouter, vLLM, LM Studio, …)."""

    # "local" = an on-machine server (Ollama or LM Studio); "cloud" = a hosted
    # OpenAI-compatible API (OpenRouter, OpenAI, Anthropic, Groq, Together, …).
    backend: str = "local"                  # "local" | "cloud"
    # Local sub-provider: "ollama" (native /api) or "lmstudio" (OpenAI /v1).
    local_provider: str = "ollama"
    # Cloud sub-provider (drives api_base_url); "custom" lets the URL be edited.
    cloud_provider: str = "openrouter"      # openrouter|openai|anthropic|groq|together|custom
    # Cloud OpenAI-compatible API (used when backend == "cloud").
    api_base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_model: str = "google/gemma-2-27b-it"

    # Local server base URL (Ollama 11434 / LM Studio 1234).
    base_url: str = "http://localhost:11434"
    # 3-way tested on a real chunk: gemma4:12b = clean; abliterated-26B = "t_t_t"
    # garbage; Qwen3.6-27B = hallucinated "@Kai", missed everyone. So 12b stays.
    # For uncensored content try "igorls/gemma-4-12B-it-heretic-GGUF:Q8_0" (12b
    # base, untested but likely coherent) — NOT the abliterated 26B.
    model: str = "gemma4:12b"
    # Per-phase model "orchestra" (local Ollama only; empty = use `model`):
    #   extraction = Pass A mention extraction (high volume — a fast small model
    #     like qwen3.5:4b); refine = Pass B speaker refine + alias merge;
    #   prompt = style bible / portrait prompts / sample lines (quality).
    extraction_model: str = ""
    refine_model: str = ""
    prompt_model: str = ""
    # Disable model "thinking" (Qwen3 etc. reason before answering, which is pure
    # overhead for schema-constrained extraction — 2-3x slower). Sent as
    # Ollama's `think: false`; ignored gracefully for non-thinking models.
    disable_thinking: bool = True
    # Concurrent per-chapter LLM calls during extraction. Real speedup needs the
    # Ollama server to allow parallelism (OLLAMA_NUM_PARALLEL>=this); otherwise
    # requests just queue. 1 = sequential (old behaviour).
    llm_concurrency: int = 4
    request_timeout_s: float = 300.0
    max_retries: int = 2
    # keep_alive controls how long Ollama keeps the model resident in VRAM.
    keep_alive: str = "5m"
    # Sampling. The abliterated model loops at very low temperature, so use a
    # moderate temperature plus a repeat penalty to break degenerate runs
    # ("...way or way or way...") that never close the JSON.
    temperature: float = 0.45
    repeat_penalty: float = 1.3
    repeat_last_n: int = 256
    # Context window: must hold prompt + structured JSON output. Ollama's
    # default (often 4096) truncates the JSON mid-string on large chunks.
    # When auto_ctx is on, the model's real max context (from /api/show) is
    # used instead, clamped to ctx_cap. NOTE: a bigger window is NOT free —
    # Ollama allocates the whole KV cache up front, so every call gets slower
    # (and too large spills to CPU). Extraction works on small chunks, so the
    # default cap stays modest; raise it only if you actually need long context.
    auto_ctx: bool = True
    ctx_cap: int = 16384
    num_ctx: int = 16384
    # Max output tokens. Ollama's default cap (128) truncates the JSON early,
    # producing an "unterminated string". Allow room for many characters.
    num_predict: int = 8192


@dataclass
class ExtractionConfig:
    """Text chunking + character map-reduce settings."""

    chunk_chars: int = 6000
    chunk_overlap_chars: int = 400
    # Optional cap for fast testing on the first few chunks (None = whole book).
    max_chunks: int | None = None
    # Mention-count ratios (relative to the most-mentioned character) used to
    # derive role_importance without asking the LLM to judge plot importance.
    main_ratio: float = 0.55
    secondary_ratio: float = 0.22
    minor_ratio: float = 0.05
    # Opt-in online research (DuckDuckGo). Breaks local-only, so off unless the
    # user enables it per run. Used to enrich style + character looks/voice.
    web_search: bool = False
    web_results: int = 5
    # Only enrich the most prominent characters online (limits requests + noise).
    web_enrich_top_n: int = 8
    # Narrator intro / closing chapters.
    front_matter: bool = True
    afterword: bool = True
    # Split a character that appears at clearly different life stages into one
    # character per age (so each gets an age-appropriate voice). Off by default:
    # the local model's per-mention age guess is noisy and over-splits.
    split_age_voices: bool = False


@dataclass
class ComfyStage:
    """A lean ComfyUI configuration for one render stage.

    Each stage loads only the custom nodes it needs (PLAN: memory-safe
    scheduler). `whitelist` maps to --whitelist-custom-nodes; empty means
    core-only (--disable-all-custom-nodes with no whitelist).
    """

    whitelist: tuple[str, ...] = ()
    sage_attention: bool = False


@dataclass
class ComfyConfig:
    """ComfyUI render backend (used for portraits + later TTS/SFX/covers)."""

    base_url: str = "http://localhost:8188"
    request_timeout_s: float = 600.0
    # Shorter cap for voice/TTS renders (they are quick) so one stuck render
    # fails fast and a batch can continue instead of appearing frozen.
    tts_timeout_s: float = 240.0
    audio_timeout_s: float = 300.0     # Stable Audio (ambience up to ~180 s)
    poll_interval_s: float = 1.0
    # Workflow templates (ComfyUI API-format graphs with {placeholders}).
    # Z-Image Turbo: fast (9 steps), natural-language prompts, has a negative
    # prompt, and avoids Ideogram's safety filter. portrait_ideogram.json is
    # kept for the JSON-caption path / later covers.
    portrait_backend: str = "z_image"          # "z_image" | "ideogram"
    portrait_workflow: str = "Z-Image_Turbo.json"
    tts_workflow: str = "Higgs_v3.json"
    voicedesign_workflow: str = "VoiceDesign.json"  # Qwen3 voice designer
    # Lean core-only Stable Audio 3 graph (no custom-node prompt enhancer).
    audio_workflow: str = "StableAudio_lean.json"
    # Fallback reference clip (must exist in ComfyUI/input/) when a character
    # has no assigned voice yet.
    default_reference_audio: str = "RiccoRecordingDE_clean.wav"

    # --- process management (lean per-stage launches) ---------------------
    # When True, the app starts/stops ComfyUI itself with only the custom
    # nodes a stage needs. When False, it assumes the user launched the right
    # workflow_launchers/*.bat and only health-checks.
    manage_process: bool = True
    comfy_dir: Path = Path(r"C:\Tools\AI\ComfyUI_windows_portable")
    startup_timeout_s: float = 180.0
    # Parallel ComfyUI instances for batch renders (each ~10 GB VRAM). 2 fits a
    # 24 GB GPU for voice/TTS. Ports are base_url's port, +1, +2, …
    parallel: int = 2
    stages: dict[str, ComfyStage] = field(
        default_factory=lambda: {
            # Z-Image portraits: core-only (resolution hardcoded in the graph).
            "image": ComfyStage(whitelist=()),
            "audio": ComfyStage(whitelist=()),   # Stable Audio 3: core only
            # NB: sage-attention can degrade Higgs cloning (wrong/female voice vs
            # a plain manual run), so the TTS stage runs with normal attention.
            "tts": ComfyStage(whitelist=("tts_audio_suite",), sage_attention=False),
        }
    )


@dataclass
class PortraitStyle:
    """Series-consistent visual style for character portraits.

    Held identical across every character so the whole cast looks like one
    coherent illustrated series (same approach as the chapter-cover bible).
    """

    aesthetics: str = "painterly character portrait, soft detail"
    lighting: str = "soft even studio light"
    medium: str = "illustration"
    art_style: str = "painterly storybook"
    color_palette: tuple[str, ...] = ("#1A2238", "#9DAAF2", "#F4DB7D", "#E0E0E0")
    background: str = "plain neutral studio backdrop, soft vignette"
    # bust/portrait framing, normalized [y_min, x_min, y_max, x_max] 0-1000
    subject_bbox: tuple[int, int, int, int] = (120, 250, 950, 750)
    width: int = 768
    height: int = 1024
    negative_prompt: str = (
        "photorealistic, photograph, photo, realistic skin pores, 3d render, "
        "nude, shirtless, undressed, bare chest, plain blank t-shirt, "
        "fashion model, supermodel, glamour, flawless skin, airbrushed, "
        "beauty retouching, perfect symmetrical face, "
        "text, watermark, deformed, extra limbs, blurry, lowres"
    )


@dataclass
class TTSConfig:
    """Speech synthesis settings. `engine` selects the backend via the registry."""

    engine: str = "higgs_v3"
    # Where the shared voice library lives (reference clips + registry).
    library_dir: Path = PROJECT_ROOT / "voices"
    # ~12-15 s of speech — Higgs needs a longer sample to judge a voice well.
    preview_text: str = (
        "Hallo, das ist eine Hörprobe meiner Stimme. Ich lese hier ein paar "
        "ruhige Sätze vor, damit man den Klang, die Betonung und das Tempo "
        "gut beurteilen kann. So lässt sich gut hören, ob diese Stimme zur "
        "Figur passt und angenehm zu hören ist."
    )
    # Emotion-varied Higgs preview: each (German line, emotion, style) is
    # rendered with its own Higgs delivery so the sample shows vocal range.
    preview_segments: list = field(default_factory=lambda: [
        ("Hallo, schön dich zu sehen.", "contentment", None),
        ("Das ist ja großartig — ich freue mich wirklich riesig!", "enthusiasm", None),
        ("Warte... hast du das eben auch gehört?", "fear", "whispering"),
        ("Manchmal wünschte ich, es wäre anders gekommen.", "sadness", None),
    ])
    language: str = "German"
    # Chapter-mix silences between line clips (ms). Tune to taste.
    chapter_gap_same_ms: int = 650     # consecutive lines, same speaker
    chapter_gap_turn_ms: int = 1150    # character <-> a different character
    # Narrator <-> dialogue flows naturally (the narrator describes, then the
    # line is spoken) so it needs a much shorter beat than character turns.
    chapter_gap_narrator_ms: int = 380
    mp3_bitrate: str = "192k"                # chapter export bitrate
    ambience_enabled: bool = True            # generate + mix ambience beds
    sfx_enabled: bool = True                 # generate + mix discrete SFX
    # How densely discrete SFX are placed: off | sparse | normal | rich. Caps
    # how many cues are attached per line and per chapter (see sfx_planner).
    sfx_density: str = "normal"
    # Ambience bed level under the dialogue (dB, negative = quieter). A radio
    # drama wants the bed clearly present, not just barely-there room tone.
    ambience_gain_db: float = -15.0
    # Scene establish: the bed swells louder for a moment at the chapter start to
    # paint the environment, then ducks to ambience_gain_db as the speaker begins.
    ambience_establish_gain_db: float = -5.0
    ambience_establish_ms: int = 2000        # ambience fades in over this, then ducks
    # Mastering: normalise each chapter mix to a target loudness (audiobook
    # range ~ -18..-23 LUFS, true-peak limited). Keeps chapters consistent.
    master_enabled: bool = True
    master_lufs: float = -19.0
    master_tp: float = -1.5            # true-peak ceiling (dBTP)
    # Intro music per chapter is disabled (chapters open with the narrator's
    # title line + an ambience establish instead). Kept configurable.
    music_enabled: bool = False
    music_gain_db: float = -3.0
    music_seconds: float = 10.0
    # Qwen3 voice designer supports only English/Chinese. We use it to create a
    # voice *timbre* sample (English), then Higgs clones it to speak German.
    design_language: str = "English"
    # Accent for the designed timbre. The book is set in England → British
    # English (otherwise Qwen defaults to American/Chinese-accented voices).
    design_accent: str = "British English"
    # Voice-sample optimize: loudness-normalise every voice to the same target
    # so all characters end up equally loud (LUFS, true-peak limited).
    voice_norm_lufs: float = -20.0
    voice_norm_tp: float = -1.5
    # De-essing intensity for the optimize step (0 = off, ~0.1-0.4 tames harsh
    # S / ß sibilance that LUFS-boosting can exaggerate). Gentle by default.
    voice_deess: float = 0.12
    # High-shelf gain (dB) above ~6 kHz applied during optimize. Negative tames
    # broadband hiss (mainly from the Enhance/super-resolution step). Off by
    # default — only needed if a sample is hissy; raise it (e.g. -4) then.
    voice_treble_db: float = 0.0
    design_reference_text: str = (
        "Hello, this is a generated voice for this character. "
        "This is how I sound when I speak calmly and clearly."
    )


@dataclass
class ExportConfig:
    """What to write into each chapter MP3's ID3 tags / metadata."""

    tag_title: bool = True            # "N. Chapter title"
    tag_album: bool = True            # book title
    tag_artist: bool = True           # author
    tag_albumartist: bool = True      # author (album artist)
    tag_track: bool = True            # track number
    tag_genre: bool = True
    genre: str = "Audiobook"
    tag_comment: bool = False
    comment: str = ""
    tag_lyrics: bool = True           # full chapter prose as USLT lyrics
    embed_cover: bool = True          # embed cover.png into every chapter MP3


@dataclass
class UIConfig:
    """Editor / display preferences."""

    show_waveforms: bool = True       # draw clip waveforms in the timeline
    waveform_opacity: int = 25        # 0..100 %


@dataclass
class AppConfig:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    comfy: ComfyConfig = field(default_factory=ComfyConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    portrait_style: PortraitStyle = field(default_factory=PortraitStyle)
    ui: UIConfig = field(default_factory=UIConfig)
    prompts_dir: Path = PROMPTS_DIR
    workflows_dir: Path = ASSET_ROOT / "workflows"
    portraits_dir: Path = DATA_ROOT / "renders" / "portraits"
    # Each imported book gets its own folder here with all its data.
    projects_root: Path = DATA_ROOT / "projects"


CONFIG = AppConfig()
