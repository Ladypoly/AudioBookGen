# Audio Drama Builder

> Repo / internal name: **AudioBookGen** · packaged app name: **Audio Drama Builder**

A local-first Windows desktop app that turns a book (**PDF / EPUB / TXT / DOCX**)
into a fully-produced **audio drama**: it extracts the cast, designs/clones
voices, generates character portraits, plans an expressive per-line script,
renders TTS + ambience + SFX, mixes everything on an editable **timeline**, and
exports a tagged audiobook.

Everything runs **locally** — [Ollama](https://ollama.com) (or any
OpenAI-compatible API) for the LLM, [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
as the render backend for image/voice/audio models. No cloud APIs are required
(an optional cloud LLM and opt-in web search aside).

---

## Contents
- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Setup](#setup)
- [Run (development)](#run-development)
- [Build the installer (.exe)](#build-the-installer-exe)
- [Configuration highlights](#configuration-highlights)
- [Model stack](#model-stack)
- [Per-book project layout](#per-book-project-layout)
- [Caveats & notes](#caveats--notes)

---

## What it does

- **Dashboard** — project grid (cover / title / author / character count). Each
  card has an **edit** action (rename, change cover, **duplicate**, **delete**).
  **New AudioDrama** flow: pick a book file → confirm dialog with editable
  cover/title/author (+ optional *auto-generate portraits & voices after
  extraction*) → animated extraction popup → lands in the project.
- **Extraction** — a multi-pass LLM pipeline (read the cast → roster → per-chapter
  storyboard/speaker-refine → style bible → portrait prompts → in-character voice
  sample lines). The popup shows **two progress bars** (overall + current task)
  and finishes with an **import report** (per-phase timings + the model each phase
  used), saved per run to compare model setups.
- **Characters** — ID-card grid (adaptive columns), sorted by spoken lines. Per
  card: portrait, role, gender/age, vocal-trait chips, a voice row (play/stop,
  upload-to-clone, design). **Age variants** as slide-dots. The edit modal also
  lets you set the **voice sample line**, a **per-character TTS engine override**,
  and **merge** another character into this one (re-points all their script lines).
  A **Generate missing** button batch-renders every missing portrait then voice
  (portraits first), and the registry always includes **default male / female /
  neutral** voices for unnamed one-off speakers.
- **Voice design** — a Qwen3-style visual editor (gender / age / pitch / speed /
  energy / emotion / style / language / timbre / accent) with a live preview and
  an editable free-form prompt. After designing the timbre, an LLM-written
  in-character intro is spoken via the clone engine to produce the playable
  **~10 s voice sample** that doubles as the clone reference.
- **Chapters** — an editable script tag-editor (select words → set emotion/style,
  assign a voice, split/merge lines; hover a line → **+ SFX**). Per-chapter
  summary + location.
- **Timeline editor** — a full-window **WYSIWYG timeline**: lanes (narrator,
  speaker, ambient, sfx, music), a round play/pause (Space), real **scrubbing**,
  **drag-to-move / drag-edges-to-trim / corner-knob fades** clips,
  **gain-scaled waveforms** that taper with the fades, and a **live Web-Audio
  mix** — what you hear is the current timeline (no re-render step). Generating a
  clip shows a progress bar; edits are baked to disk on close for export.
- **Render / produce / export** — per-chapter or all-chapters render; export
  tagged MP3s + cover to a folder.
- **Settings** — backend (local **Ollama**/LM Studio or **cloud** OpenAI-compatible
  with a priced model picker), the **extraction model orchestra** (per-phase
  model + concurrency + disable-thinking), selectable **voice-design / voice-clone
  workflows** (Higgs / Qwen / OmniVoice), waveform options, audio mix levels, and
  more.
- **First-run setup wizard** — scans Ollama, asks for the ComfyUI path, checks the
  `tts_audio_suite` node, and offers a one-click clone + pip-install.

---

## Architecture

```
┌─ Electron shell (electron/) ────────────────────────────────┐
│  React + TS + Vite + Tailwind frontend (frontend/)          │
│        │ REST (CRUD) + WebSocket /ws/jobs (progress)        │
│  ┌─────▼──────────────────────────────────────────────────┐ │
│  │ FastAPI sidecar (server/) — thin layer over app/*      │ │
│  │   routers/ + jobs.py (async job runner) + serves media │ │
│  └────────────────────────────────────────────────────────┘ │
│       app/services/* + app/schemas/*  (the Python pipeline)  │
└──────────────────────────────────────────────────────────────┘
        ↓ HTTP                         ↓ HTTP
     Ollama / cloud LLM            ComfyUI (render backend)
```

- **`app/`** — the Python pipeline. `services/` + `schemas/` are UI-agnostic.
- **`server/`** — FastAPI bridge. `jobs.py` runs blocking pipeline calls on a
  thread pool and streams progress over `/ws/jobs`.
- **`frontend/`** — the React app (the active UI).
- **`electron/`** — desktop shell: spawns the sidecar, hosts the frontend,
  provides native dialogs, bundles ffmpeg.
- **`app/ui/` + `app/workers/`** — the **legacy** PySide6 UI, kept but no longer
  the focus.

See [DEV_WEB.md](DEV_WEB.md) for the dev loop and [BUILD.md](BUILD.md) for
packaging detail.

---

## Requirements

- **Windows 10/11** (the app drives a Windows ComfyUI portable and uses
  Windows-only process management).
- **Python 3.11** (tested with miniconda).
- **Node + npm** (frontend + electron-builder).
- **ffmpeg** on `PATH` (dev) or in `electron/ffmpeg/` (packaged) — pydub needs it
  for MP3 mixing/export.
- **LLM**: local **Ollama** at `localhost:11434` (free) **or** a cloud
  OpenAI-compatible API. A model with clean structured-output support is needed
  (`gemma4:12b` is known-good; `qwen3.5:4b` is a fast option for the high-volume
  cast pass — see [the orchestra](#configuration-highlights)).
- **ComfyUI** portable (default path `C:\Tools\AI\ComfyUI_windows_portable`) with
  the **`tts_audio_suite`** custom node and the model weights for the stages you
  use.

GPU steps (portrait / voice / TTS / ambience / SFX) need ComfyUI running. The
non-GPU paths (extraction with a cloud LLM, script/tag editing, timeline arrange,
mix-only render, export) work without it.

---

## Setup

```bash
git clone <this-repo> && cd AudioBookGen

# 1. Python deps (use the interpreter you'll run the sidecar with)
pip install -r requirements.txt

# 2. Frontend deps
cd frontend && npm install && cd ..

# 3. (for the desktop shell) Electron deps
cd electron && npm install && cd ..
```

**LLM** — install [Ollama](https://ollama.com) and pull a model:

```bash
ollama pull gemma4:12b          # known-good for structured extraction
ollama pull qwen3.5:4b          # optional: fast model for the cast pass
# For real parallel speedup, allow concurrent requests:
setx OLLAMA_NUM_PARALLEL 6
```

**ComfyUI** — install the portable build, then add the TTS node:

```bash
cd <ComfyUI_portable>\ComfyUI\custom_nodes
git clone --depth 1 https://github.com/diodiogod/TTS-Audio-Suite tts_audio_suite
<ComfyUI_portable>\python_embeded\python.exe -m pip install -r tts_audio_suite\requirements.txt
```

> The in-app **first-run setup wizard** can do the ComfyUI-path + `tts_audio_suite`
> install for you (clone + pip) with a live log.

**ffmpeg** — put `ffmpeg.exe` (+ `ffprobe.exe`) on `PATH` for dev, or drop them
into `electron/ffmpeg/` for the packaged app.

---

## Run (development)

Two terminals:

```bash
# 1. FastAPI sidecar  → http://127.0.0.1:8765
python -m server.main

# 2. Vite dev server  → http://localhost:5173  (proxies /api + /ws to the sidecar)
cd frontend && npm run dev
```

Open <http://localhost:5173>.

Or run the **desktop shell** (Electron spawns the sidecar itself):

```bash
cd frontend && npm run build      # build frontend/dist first
cd ../electron && npm run dev      # loads the Vite dev server with DevTools
# or: npm run start                # loads the built bundle
```

> If `python` isn't on `PATH`, set `ABG_PYTHON` to the interpreter that has the
> deps, e.g. `setx ABG_PYTHON C:\Users\You\miniconda3\python.exe` — used by both
> the Electron shell and the build script.

The legacy Qt UI still runs via `run_app.bat` (`python -m app.main`).

---

## Build the installer (.exe)

```powershell
build_installer.bat
# or: powershell -ExecutionPolicy Bypass -File build/build_installer.ps1
```

Output: `installer/Audio-Drama-Builder-Setup-<version>.exe` — a self-contained
NSIS installer (frozen FastAPI sidecar + frontend + prompts/workflows + bundled
ffmpeg; **no system Python needed** on the target). The build **auto-bumps the
patch version** each run.

Pipeline: build the frontend → freeze the sidecar with PyInstaller
(`build/sidecar.spec`) → package with electron-builder
(`electron/package.json` → `build`). Full detail in [BUILD.md](BUILD.md).

What it does **not** bundle: Ollama, ComfyUI, the `tts_audio_suite` node, and the
model weights — those stay external on the target machine. The `.exe` is
**unsigned**, so Windows SmartScreen shows a warning (*More info → Run anyway*).
Installed user data lives in `%APPDATA%/Audio Drama Builder/`
(`projects/`, `settings.json`).

Faster inner loop (unpacked, no installer):

```powershell
npm --prefix electron run pack    # → installer/win-unpacked/
```

---

## Configuration highlights

- **LLM backend** — local Ollama / LM Studio, or a cloud OpenAI-compatible API
  (OpenRouter / OpenAI / Anthropic / Groq / Together / custom) with a searchable,
  priced model picker.
- **Extraction model "orchestra"** (Settings → LLM, local only) — pick a separate
  model **per phase**: a fast small model for the high-volume **cast pass**
  (e.g. `qwen3.5:4b`) and your main model for refine / prompts. Empty = use the
  main model.
- **Disable thinking** (Settings → Performance) — sends Ollama's `think: false`.
  On by default: schema-constrained extraction doesn't need reasoning, and some
  thinking models otherwise return empty JSON. Harmless for non-thinking models.
- **Extraction concurrency** — runs the per-chapter LLM calls in parallel (pair
  with `OLLAMA_NUM_PARALLEL`).
- **Voice-design / voice-clone workflows** (Settings → Workflows) — dropdowns of
  the templates in `workflows/`: **Higgs**, **Qwen**, or **OmniVoice**. The clone
  workflow can also be **overridden per character** (e.g. fast no-emotion
  OmniVoice for the narrator, expressive Higgs for characters). Emotion tags are
  emitted per engine automatically (OmniVoice drops unsupported tags).

---

## Model stack

| Role | Model | Backend |
|------|-------|---------|
| LLM extraction / style / prompts / summaries | `gemma4:12b` (+ optional `qwen3.5:4b` for the cast pass) or any cloud model | Ollama / OpenAI-compatible API |
| Character portraits | Z-Image Turbo | ComfyUI (core nodes) |
| Voice design (timbre) | Qwen3 TTS Voice Designer **or** OmniVoice | ComfyUI (tts_audio_suite) |
| TTS / voice cloning | Higgs Audio v3 **or** OmniVoice | ComfyUI (tts_audio_suite) |
| SFX / ambience / music | Stable Audio | ComfyUI (core nodes) |

**Voice is two-step**: a designer creates a timbre sample → a clone engine speaks
the script in that timbre. Both stages are swappable per the Workflow settings.

---

## Per-book project layout

```
projects/<book-slug>/
  project.json                 title, author, subtitle, source_file
  cover.png
  source/                      copy of the book file
  analysis/
    mentions.json, grouped.json, registry.json    (extraction QC)
    import_reports.json        per-run import timings (model comparison)
    chapters/<id>.json         Chapter (text, lines, summary, location, curated)
    chapters/<id>.timeline.json  derived/edited WYSIWYG timeline
    chapters/index.json
  registry/characters.json     the cast (variants, voice assignments, portraits)
  style/style_bible.json
  renders/portraits/<id>.png   (+ .json prompt sidecar)
  renders/tts/<chapter>/<line>.mp3
  voices/<id>.mp3, <id>_preview.mp3
  mixes/chapters/<id>.mp3 | ambience/ | sfx/ | music/ | timeline/
```

Project data lives under `DATA_ROOT/projects` — the repo root in dev, or
`%APPDATA%/Audio Drama Builder/` in the installed app (`ABG_DATA_ROOT`).

---

## Caveats & notes

- **ffmpeg required** at runtime (pydub MP3 ops). On `PATH` in dev; bundled in the
  installer.
- **voice-optimize** (Demucs/DeepFilterNet/VoiceFixer denoise) is torch-based and
  **excluded from the packaged sidecar** — it degrades gracefully (skips).
- **Web search is off by default.** `research_service.py` scrapes DuckDuckGo's
  HTML endpoint (snippets only) and rate-limits quickly; for real web context
  point it at a self-hosted SearXNG or a keyed API.
- The PyInstaller spec **excludes the heavy ML stack** (torch, transformers,
  cv2, …) — the sidecar only drives ComfyUI/Ollama over HTTP.
- The **legacy PySide6 UI** (`app/ui/`, `app/workers/`) is kept but no longer the
  focus; new work goes through `server/` + `frontend/`.

### Key references
- [DEV_WEB.md](DEV_WEB.md) — run the web stack.
- [BUILD.md](BUILD.md) — package the installer.
- `PLAN.txt` — original product spec + engine prompting contracts.
- `memory/` — cross-session notes (model choices, etc.).
