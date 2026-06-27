@echo off
REM Run AudioBookGen in browser dev mode (no build / freeze / installer).
REM Opens two windows: FastAPI sidecar + Vite frontend dev server.
REM   Backend : http://127.0.0.1:8765
REM   Frontend: http://localhost:5173   <-- open this in your browser

setlocal
cd /d "%~dp0"

REM Use a specific Python if ABG_PYTHON isn't already set (the verified env).
if not defined ABG_PYTHON set "ABG_PYTHON=C:\Users\Elin\miniconda3\python.exe"
if not exist "%ABG_PYTHON%" set "ABG_PYTHON=python"

echo Using Python: %ABG_PYTHON%
echo.

REM 1) Backend sidecar (FastAPI) in its own window.
start "ABG backend (sidecar)" cmd /k ""%ABG_PYTHON%" -m server.main"

REM 2) Frontend dev server (installs deps on first run) in its own window.
start "ABG frontend (vite)" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev"

echo.
echo Two windows launched:
echo   - ABG backend (sidecar)   http://127.0.0.1:8765
echo   - ABG frontend (vite)     http://localhost:5173
echo.
echo Open http://localhost:5173 in your browser once Vite is ready.
echo Close those two windows to stop the app.
echo.
pause
endlocal
