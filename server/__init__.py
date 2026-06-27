"""FastAPI bridge over the existing app/services pipeline.

The desktop UI is a web frontend (React/Electron); this package exposes the
Python pipeline as a local HTTP + WebSocket API. All real work still lives in
`app/services/*` — routers and jobs are thin wrappers that call them and stream
progress over the `/ws/jobs` channel (replacing the old Qt QThread/Signal UI).
"""
