# Web UI (React + Electron) — dev guide

The UI is being reworked from PySide6 to a web frontend over a FastAPI bridge.
The old `app/ui/*` (PySide6) still exists; the new stack lives in `server/`,
`frontend/`, and `electron/`.

```
server/      FastAPI bridge over the existing app/services/* pipeline
frontend/    React + TS + Vite + Tailwind (the new UI)
electron/    Desktop shell: spawns the sidecar, hosts the frontend
```

## Run in the browser (fastest dev loop)

Two terminals:

```bash
# 1. backend sidecar (FastAPI) on http://127.0.0.1:8765
python -m server.main

# 2. frontend dev server on http://localhost:5173 (proxies /api + /ws to the sidecar)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173.

## Run as the desktop app (Electron)

```bash
cd frontend && npm run build      # builds frontend/dist
cd ../electron && npm install
npm run start                     # spawns the sidecar + opens the window
# or: npm run dev                 # loads the Vite dev server with DevTools
```

Electron injects `window.__API_BASE__ = http://127.0.0.1:8765` so the renderer
talks to the sidecar directly (CORS is open for local use). It also exposes
native dialogs via `window.electronAPI` (open book file, choose export folder).

## API surface (M1)

| Route | Purpose |
|-------|---------|
| `GET /api/ping` | liveness |
| `GET /api/health` | Ollama + ComfyUI status (top status bar) |
| `GET /api/projects` | dashboard project list |
| `POST /api/projects/{id}/open` | set active project |
| `GET /api/settings/schema` | settings sections + fields + values |
| `POST /api/settings` | save settings |
| `GET /api/media/{rel}` | serve project covers/portraits/audio |
| `WS /ws/jobs` | live job progress (queue strip) |

Jobs replace the old `app/workers/*` QThread layer — see `server/jobs.py`
(`JobManager` + `JobContext`). Pipeline work runs on a thread pool and streams
progress to every `/ws/jobs` client.
