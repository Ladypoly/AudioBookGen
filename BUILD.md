# Building the AudioBookGen installer (.exe)

Produces a Windows NSIS installer (`AudioBookGen-Setup-<version>.exe`) that
installs a self-contained desktop app — **no system Python required** on the
target machine. ComfyUI and Ollama remain external (the app talks to them over
HTTP, as in dev).

## One command

```powershell
# from the repo root
powershell -ExecutionPolicy Bypass -File build/build_installer.ps1
```

Output: `installer/AudioBookGen-Setup-<version>.exe`.

## What it does

1. **Frontend** — `npm --prefix frontend run build` → `frontend/dist`.
2. **Sidecar** — PyInstaller freezes `server.main` (and the whole
   `app/services` pipeline) → `dist_sidecar/abg-sidecar/abg-sidecar.exe`
   (see `build/sidecar.spec`).
3. **Package** — electron-builder bundles the frontend, the frozen sidecar,
   `prompts/` + `workflows/` (as `resources/assets`), and `electron/ffmpeg/`
   into an NSIS installer (config in `electron/package.json` → `build`).

## Prerequisites

```bash
pip install -r requirements.txt pyinstaller
```

- **Node + npm** (for the frontend and electron-builder).
- **ffmpeg** — drop `ffmpeg.exe` into `electron/ffmpeg/` (see the README there).
  Without it the app runs but audio mastering is skipped.
- If `python` isn't on PATH, set `ABG_PYTHON` to the interpreter that has the
  deps installed, e.g. `setx ABG_PYTHON C:\Users\You\miniconda3\python.exe`.

## Runtime layout (installed app)

| Path | Contents |
|------|----------|
| `resources/sidecar/abg-sidecar.exe` | frozen FastAPI server |
| `resources/frontend/` | built React bundle |
| `resources/assets/{prompts,workflows}` | bundled read-only assets (`ABG_ASSET_ROOT`) |
| `resources/ffmpeg/` | bundled ffmpeg (added to PATH) |
| `%APPDATA%/AudioBookGen/` | user data — `projects/`, `settings.json` (`ABG_DATA_ROOT`) |

The Electron main process (`electron/main.cjs`) spawns the sidecar with those
env vars set, waits for `/api/ping`, then loads the frontend.

## Faster inner loop (no installer)

```powershell
npm --prefix electron run pack   # unpacked app in installer/win-unpacked/
```

## Note on build size / time

The first build downloads Electron + electron-builder (~hundreds of MB) and a
PyInstaller pass takes a few minutes; both are normal for a desktop bundle.
