# Book2AudioDrama (AudioBookGen)

Local-first Windows desktop app that turns a book (PDF / EPUB / TXT / DOCX) into
an automated **audio drama**: it extracts the cast, designs/clones voices,
generates portraits, plans an expressive per-line script, renders TTS + ambience
+ SFX, mixes everything on an editable **timeline**, and exports a tagged
audiobook.

Everything runs **locally** — Ollama (or any local/cloud OpenAI-compatible API)
for the LLM, ComfyUI as the render backend for image/voice/audio models. No
cloud APIs are required (an optional cloud LLM and opt-in web search aside).

> **Big picture for a new contributor:** the UI was reworked from PySide6 to a
> **web stack** — a React/Electron frontend talking to a **FastAPI sidecar** that
> wraps the existing Python pipeline. The old PySide6 UI (`app/ui/`, `app/main.py`)
> still exists and runs, but the **web UI is the active product**. See
> [DEV_WEB.md](DEV_WEB.md) to run it and [BUILD.md](BUILD.md) to package it.

---

## Architecture (current)

```
┌─ Electron shell (electron/) ────────────────────────────────┐
│  React + TS + Vite + Tailwind frontend (frontend/)          │
│   • shell: sidebar nav, top status bar, bottom queue strip  │
│   • screens: Dashboard, Characters, Chapters, Settings      │
│   • timeline editor, tag editor, voice-design popup         │
│        │ REST (CRUD) + WebSocket /ws/jobs (progress)        │
│  ┌─────▼──────────────────────────────────────────────────┐ │
│  │ FastAPI sidecar (server/) — thin layer over app/*      │ │
│  │   routers/ + jobs.py (async job runner, replaces Qt)   │ │
│  │   serves project media (covers, portraits, audio)      │ │
│  └────────────────────────────────────────────────────────┘ │
│       app/services/* + app/schemas/* (reused unchanged)      │
└──────────────────────────────────────────────────────────────┘
        ↓ HTTP                         ↓ HTTP
     Ollama / cloud LLM            ComfyUI (render backend)
```

- **`app/`** — the Python pipeline. `services/` and `schemas/` are UI-agnostic and
  shared by both the old Qt UI and the new sidecar. `app/workers/` (QThread) is
  **superseded** by `server/jobs.py` for the web UI.
- **`server/`** — FastAPI bridge. Routers wrap services; `jobs.py` runs blocking
  pipeline calls on a thread pool and streams progress over `/ws/jobs`.
- **`frontend/`** — the React app (the real UI).
- **`electron/`** — desktop shell: spawns the sidecar, hosts the frontend,
  provides native file/folder dialogs, bundles ffmpeg.

### Source map
```
app/
  core/config.py          all settings (UIConfig, OllamaConfig, TTSConfig, …)
  schemas/                pydantic models (single source of truth)
    characters.py         Character (+ CharacterVariant for age stages)
    script.py             Chapter, LineItem (+ origin/pitch), SfxCue (+ fades/custom)
    voice.py              Delivery (Higgs enum-locked), Voice
    timeline.py           Timeline + TimelineSegment (the WYSIWYG edit model)
    style.py              StyleBible
  services/
    pdf_service.py        multi-format extract (pdf/epub/docx/txt) + cover + chunk
    book_meta.py          embedded title/author/cover; chapter MP3 tagging
    ollama_service.py     LLM client: local (Ollama) OR cloud (OpenAI-compatible)
    cost_service.py       token-cost estimate from the active model's pricing
    character_service.py  map -> merge -> roles -> descriptions; age-variant split
    story_service.py      chapter-centric extraction orchestrator
    chapter_service.py    chapter detect + persistence (analysis/chapters/)
    chapter_brief.py      per-chapter summary + location (1 LLM call)
    line_planner.py       prose -> ordered LineItems (speaker, delivery)
    chapter_render.py     render lines -> mix (gaps/sfx/ambience/pitch) -> master
    timeline_service.py   derive/persist timeline.json; build mix FROM it (WYSIWYG)
    ambience.py / sfx_planner.py / music_planner.py / sound_service.py
    voice_design.py       Qwen3 voice designer; compose_description (full controls)
    voice_optimize.py     optional denoise/normalize (torch libs; degrades if absent)
    portrait_service.py   Z-Image prompt build + render
    comfy_service.py      ComfyUI API client (fill workflow, WS progress, fetch)
    comfy_launcher.py     lean per-stage ComfyUI process manager
    project_service.py    per-book folders, create/open/activate, save/load
    audiobook_export.py   export tagged MP3s + cover to a folder
    tts/                  TTSEngine protocol + Higgs engine + tag_builder
  workers/                LEGACY QThread workers (used only by the old Qt UI)
  ui/                     LEGACY PySide6 UI (app/main.py)
server/
  main.py                 FastAPI app (port 8765)
  jobs.py                 JobManager + JobContext + /ws/jobs hub
  extraction.py           extraction pipeline as a job (step events for the popup)
  rendering.py            chapter render / produce-all / export / timeline render jobs
  routers/                health, projects, ingest, characters, chapters, settings, media, jobs
frontend/                 React + Vite + TS + Tailwind (src/app, src/screens, src/lib)
electron/                 main.cjs, preload.cjs, ffmpeg/ (bundled), package.json (electron-builder)
build/                    sidecar.spec (PyInstaller), build_installer.ps1
prompts/                  versioned prompt text files
workflows/                ComfyUI API-format graphs with {placeholders}
projects/<book-slug>/     per-book data (created at runtime; gitignored)
```

---

## What works today (web UI)

- **Dashboard** — project grid (cover/title/author/char count); **New AudioDrama**
  flow: pick a pdf/epub/txt/docx → confirm dialog with **editable cover/title/author**
  → animated-step **extraction popup** → lands in project view.
- **Characters** — **ID-card** redesign. Per-character: portrait, role badge,
  gender/age, vocal-trait chips, voice row (play / upload-to-clone / design).
  **Age variants** (`CharacterVariant`) show as **slide-dots** that swap
  portrait + description + voice; full manual edit modal (incl. adding ages).
- **Voice design popup** — clicking **Design** opens a Qwen3-style visual editor:
  Gender / Age / Pitch / Speed / Energy / Emotion / Style / Language (10) /
  Timbre (multi) / Accent, with a live `OUT >` preview and an **editable free-form
  prompt** (Qwen voice design is natural-language driven). Tweak → regenerate.
- **Chapters**
  - **Editable script as a tag editor** — select words → popup to set **emotion /
    style** and **assign a voice** (existing character, or a shared **Default
    male/female** voice with a **pitch** offset for unnamed one-off speakers).
    Partial selections **split** the line into their own segment; clearing tags
    **re-merges** back to the original sentence. Hover a line → **+ SFX** (drag an
    audio file or type a prompt to generate).
  - **Per-chapter summary + location** header (1 LLM call).
  - **Open timeline editor** → full-window **WYSIWYG timeline**: lanes (bottom→top)
    narrator, speaker, ambient, sfx, **music**; **play/pause + seek bar + scrubbable
    playhead**; **waveforms** (~25%, toggle + opacity in Settings); clips are
    **selectable, drag-to-move, editable** (prompt/gain/fades/duration),
    **regenerate** (ambient/sfx/music) / **delete** / **add**. All edits persist to
    `timeline.json` and the mix is rebuilt from it (`Re-render from timeline`).
- **Render / produce / export** — per-chapter or all-chapters render with modes
  (full / continue / voices / mix / …); export tagged MP3s + cover to a folder.
- **Settings** — bottom-left, left-nav sections. **LLM section is a custom panel**:
  **Local** (Ollama / LM Studio, with an installed-model dropdown) or **Cloud API**
  (OpenRouter / OpenAI / Anthropic / Groq / Together / custom, with a **searchable
  model picker showing price + cheap/medium/expensive tier**).
- **Token-cost estimates** — every LLM job shows an estimate in the queue strip
  (`free` for local; `~$X` for cloud, from the model's pricing).
- **Lean per-stage ComfyUI** — launches headless with only the nodes a stage needs,
  unloads Ollama first so the GPU is never shared; stops on app close.

---

## Run (development)

Two terminals (see [DEV_WEB.md](DEV_WEB.md)):

```bash
python -m server.main                 # FastAPI sidecar on http://127.0.0.1:8765
cd frontend && npm install && npm run dev   # Vite on http://localhost:5173 (proxies /api + /ws)
```

Open http://localhost:5173. Or run the desktop shell:

```bash
cd frontend && npm run build
cd ../electron && npm install && npm run dev   # spawns the sidecar + opens the window
```

The legacy Qt UI still runs via `run_app.bat` (`python -m app.main`).

## Build the installer (.exe)

```powershell
build_installer.bat        # or: powershell -File build/build_installer.ps1
```

Produces `installer/AudioBookGen-Setup-<ver>.exe` (self-contained: frozen
FastAPI sidecar + frontend + prompts/workflows + bundled ffmpeg; no system
Python needed). See [BUILD.md](BUILD.md). Notes:
- The PyInstaller spec (`build/sidecar.spec`) **excludes the heavy ML stack**
  (torch, transformers, cv2, …) — the sidecar only drives ComfyUI/Ollama over
  HTTP, so bundling them is unnecessary and blew NSIS's 2 GB mmap limit.
- Put `ffmpeg.exe`/`ffprobe.exe` in `electron/ffmpeg/` (already done on this
  machine) — pydub needs ffmpeg for MP3 mixing/export.

---

## Requirements

- Windows, Python 3.11 (tested with miniconda). `pip install -r requirements.txt`
  (fastapi, uvicorn, python-multipart, pymupdf, ebooklib, python-docx,
  beautifulsoup4, pillow, httpx, pydantic, pydub, mutagen, …). For building also
  `pip install pyinstaller`.
- Node + npm (frontend + electron-builder).
- **ffmpeg** on PATH (dev) or in `electron/ffmpeg/` (packaged).
- **LLM**: local **Ollama** at `localhost:11434` (free) **or** a cloud
  OpenAI-compatible API (set in Settings → LLM). Extraction needs a model with
  clean structured-output support (`gemma4:12b` is known-good locally).
- **ComfyUI** portable at `C:\Tools\AI\ComfyUI_windows_portable` with
  `tts_audio_suite` (Higgs v3 + Qwen3 designer), Z-Image Turbo, Stable Audio 3.

---

## Model stack

| Role | Model | Backend |
|------|-------|---------|
| LLM extraction / style / prompts / summaries | `gemma4:12b` (local) or any cloud model | Ollama / OpenAI-compatible API |
| Character portraits | Z-Image Turbo | ComfyUI (core nodes) |
| Voice design (timbre) | Qwen3 TTS Voice Designer | ComfyUI (tts_audio_suite) |
| TTS / voice cloning | Higgs Audio v3 | ComfyUI (tts_audio_suite) |
| SFX / ambience / music | Stable Audio 3 | ComfyUI (core nodes) |

**Voice is two-step**: Qwen3 designs a timbre sample → Higgs clones it to speak
**German**. The voice-design popup exposes Qwen's full natural-language control
surface (timbre, prosody, emotion, persona, gender, age, accent, pacing, energy,
language); the final spoken language still comes from the Higgs stage.

---

## Per-book project layout

```
projects/<book-slug>/
  project.json                 title, author, subtitle, source_file
  cover.png
  source/                      copy of the book file
  analysis/
    mentions.json, grouped.json, registry.json   (extraction QC)
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

---

## Spoiler-safe

Extraction reads the whole book but the registry is built spoiler-light at the
source (firewall prompts forbid plot/fate/reveals); only names, roles, voice and
neutral appearance are surfaced. Web enrichment uses snippets only.

---

## Known caveats / next steps

- **ffmpeg is required** at runtime (pydub MP3 ops). On PATH in dev; bundled in
  the installer.
- **voice-optimize** (Demucs/DeepFilterNet/VoiceFixer denoise) is torch-based and
  is **excluded from the packaged sidecar** — it degrades gracefully (skips).
- **GPU steps need ComfyUI running** (portrait/voice/TTS/ambience/SFX). The
  non-GPU paths (extraction with a cloud LLM, script/tag editing, timeline
  arrange, mix-only render, export) work without it.
- **Web search is off by default and intentionally so.** `research_service.py`
  scrapes DuckDuckGo's HTML endpoint (snippets only — it never visits target
  sites). DDG rate-limits the scraper after ~7 rapid queries (HTTP 202 + empty),
  so a full enrichment run silently gets nothing for its back half; it fails
  soft (returns `[]`), the pipeline falls back to LLM-only inference. Leave it
  off; if real web context is wanted, point `research_service.search()` at a
  self-hosted **SearXNG** (`/search?format=json`, local + no key) or a keyed API
  (Tavily/Brave) rather than the raw DDG scrape.
- The **legacy PySide6 UI** (`app/ui/`, `app/workers/`) is kept but no longer the
  focus; new work goes through `server/` + `frontend/`.
- Animated `.webp` assets for the extraction-popup steps are placeholders
  (`frontend/public/steps/<key>.webp` slots) until provided.

## Key references
- [DEV_WEB.md](DEV_WEB.md) — run the web stack. [BUILD.md](BUILD.md) — package it.
- `PLAN.txt` — original product spec + engine prompting contracts (Appendices A/B).
- Latest rework plan: `~/.claude/plans/so-the-new-ui-tidy-comet.md`.
- `memory/` — cross-session notes (model choices, etc.).
