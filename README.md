# Book2AudioDrama

Local-first Windows desktop app that turns a German book PDF into an automated
audio drama: it extracts the cast, designs/clones voices, generates character
portraits, and (planned) renders expressive TTS, SFX/music, mixing and export.

Everything runs **locally** — Ollama for the LLM, ComfyUI as the render backend
for image/voice models. No cloud APIs are required (optional web search aside).

---

## Status

### Working today
- **Dashboard** — lists stored projects (title + character count), open / create.
- **Character extraction** — PDF → cleaned text → chunked → LLM map pass →
  code-side merge → **speaking-role cast** with role, gender/age guess, voice
  hint, appearance description. Streams cards live while reading.
- **Per-book projects** — each book gets its own folder with everything in it
  (source, analysis, registry, style bible, portraits, voices).
- **Style Bible** — one LLM pass derives a consistent, book-fitting visual style
  (genre, palette, casting, wardrobe, backgrounds) used across all portraits.
- **Character portraits** — Z-Image Turbo via ComfyUI. Per-character LLM-written
  prompts (varied clothing/background) wrapped in a *fixed* style block so the
  whole cast looks consistent. Live sampler progress.
- **Voices**
  - **Drag-and-drop** an audio file (wav/mp3/ogg/flac/m4a) onto a character card
    → copied into the project, set as that character's voice.
  - **Generate** — Qwen3 voice designer creates a voice from the character
    profile (2-step: Qwen designs the timbre → Higgs speaks German).
  - **Play/Stop** — Higgs renders a ~15 s German preview (clones the voice),
    played in-app.
- **Lean per-stage ComfyUI** — the app launches ComfyUI headless with only the
  custom nodes a stage needs, and unloads Ollama first, so the 24 GB GPU is
  never shared. Closing the app stops ComfyUI.
- **Optional web search** (DuckDuckGo, opt-in) to enrich style + character looks.

### Not yet built
- Pass-4 (LLM writes per-line delivery metadata) and scene/chapter TTS rendering
- SFX / music generation wired into the pipeline (Stable Audio 3 workflow ready)
- Mixing, mastering, export (WAV/MP3/M4B)
- Chapter covers screen, Settings/Diagnostics screens, QC dashboard

---

## Requirements

- Windows, Python 3.11 (tested with the user's miniconda env)
- **Ollama** running at `localhost:11434` with `gemma4:12b` pulled
- **ComfyUI** portable at `C:\Tools\AI\ComfyUI_windows_portable` with:
  - `tts_audio_suite` custom nodes (Higgs v3 + Qwen3 designer)
  - Z-Image Turbo model (`z_image_turbo_bf16.safetensors`) + deps
  - Stable Audio 3 model (for later SFX/music)
- Python deps: `pip install -r requirements.txt`
  (PySide6, pymupdf, httpx, pydantic, websocket-client)

## Run

```
run_app.bat
```
or `python -m app.main` from the project root.

Flow: **Dashboard** → New project (choose PDF) → **Characters** → Test mode (first
N chunks) → *Extract Characters* → *Generate all portraits* → drop or *Generate*
a voice per card → ▶ to hear it.

> First portrait/voice render is slow (ComfyUI launch + model load, ~50 s);
> later ones reuse the warm model (~20 s).

---

## Model stack

| Role | Model | Backend |
|------|-------|---------|
| LLM extraction / style / prompts | `gemma4:12b` | Ollama |
| Character portraits | Z-Image Turbo | ComfyUI (core nodes) |
| Voice design (timbre) | Qwen3 TTS Voice Designer | ComfyUI (tts_audio_suite) |
| TTS / voice cloning | Higgs Audio v3 | ComfyUI (tts_audio_suite) |
| SFX / music (planned) | Stable Audio 3 | ComfyUI (core nodes) |

**Model notes**
- `gemma4:12b` is the only model that gave clean structured output. The
  abliterated 26B and Qwen3.6-27B both produced garbage and were rejected
  (see `memory/`). Uncensored fallback: `gemma-4-12B-it-heretic`.
- Ollama options that matter: `num_ctx 16384`, `num_predict 8192`,
  `repeat_penalty 1.3`, `temperature ~0.45`; schema strings are length-capped.
- **Voice is two-step**: Qwen3 designs an English timbre sample (it only speaks
  English/Chinese) → Higgs clones it to speak **German**. The accent is German
  because Higgs produces the German speech.

---

## Architecture

```
app/
  main.py                 entry point
  core/
    config.py             all settings (one place to tweak)
    prompts.py            prompt-file loader
  schemas/                pydantic models (single source of truth)
    characters.py         Character, mentions, enums (gender/age/role)
    style.py              StyleBible
    voice.py              Voice, Delivery (Higgs enum-locked)
  services/
    pdf_service.py        extract + chunk
    ollama_service.py     LLM client (structured outputs, retries, unload)
    character_service.py  map -> code-merge -> roles -> descriptions, web enrich
    style_service.py      Style Bible generation
    research_service.py   DuckDuckGo (opt-in)
    portrait_service.py   Z-Image prompt build + render
    voice_design.py       Qwen3 voice designer (provider)
    comfy_service.py      ComfyUI API client (fill workflow, WS progress, fetch)
    comfy_launcher.py     lean per-stage ComfyUI process manager
    project_service.py    per-book folders, save/load, list
    tts/
      base.py             TTSEngine protocol  <- swap point
      tag_builder.py      Delivery -> Higgs <|...|> tokens
      higgs.py            HiggsTTSEngine
      registry.py         get_engine(name)
  workers/                QThread workers (extract, portrait, batch, tts, design)
  ui/                     dashboard, characters screen, character card, flow
prompts/                  versioned prompt + rewriter text files
workflows/                ComfyUI API-format graphs with {placeholders}
projects/<book-slug>/     per-book data (created at runtime)
memory/                   cross-session notes (model choice, etc.)
```

### Modularity (swap points)
- **TTS engine** — implement `tts/base.TTSEngine`, register in `tts/registry.py`,
  set `CONFIG.tts.engine`. Higgs is the only knower of its tag syntax
  (`tag_builder.py`).
- **Voice design** — `voice_design.py` is a separate provider; workflow name in
  config.
- **ComfyUI graphs** — live in `workflows/*.json` with `{placeholders}`; change
  nodes without touching code. Stage → custom-node whitelist in `config.py`.
- **Prompts** — all in `prompts/*.txt`, loaded by name, versioned in a header.

---

## Per-book project layout

```
projects/<book-slug>/
  project.json            title + source path
  source/                 copy of the PDF
  analysis/               mentions.json, grouped.json, registry.json (QC)
  registry/characters.json   the cast (with voice assignments + portrait paths)
  style/style_bible.json
  renders/portraits/<character_id>.png  (+ .json prompt sidecar)
  voices/<character_id>.<ext>           assigned/designed voice sample
```

---

## Spoiler-safe

Extraction reads the whole book but the registry is built spoiler-light at the
source (firewall prompts forbid plot/fate/reveals); only names, roles, voice and
neutral appearance are surfaced. Web enrichment uses snippets only and the same
firewall.

---

## Key references

- Engine prompting contracts (Higgs tags, Ideogram/Z-Image, Stable Audio): see
  `PLAN.txt` Appendices A & B.
- Per-engine ComfyUI launchers: `C:\Tools\AI\ComfyUI_windows_portable\workflow_launchers\`
  (`run_Ideogram.bat`, `run_StableAudio.bat`, `run_TTS.bat`).
