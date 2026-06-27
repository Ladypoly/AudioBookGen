# Bundled ffmpeg

Place **`ffmpeg.exe`** (and optionally `ffprobe.exe`) in this folder before
building the installer. They get packaged into the app's `resources/ffmpeg/`
folder and added to the sidecar's `PATH`, so audio mixing/mastering (pydub +
ffmpeg loudnorm) works without a system-wide ffmpeg install.

Get a static Windows build from https://www.gyan.dev/ffmpeg/builds/ (the
"essentials" build is enough) and copy `bin/ffmpeg.exe` here.

This folder is intentionally kept in the repo (with this README) so the
electron-builder `extraResources` entry always has a directory to copy. If
`ffmpeg.exe` is missing, the app still runs but mastering is skipped.
