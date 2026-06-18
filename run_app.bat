@echo off
REM Launch Book2AudioDrama desktop UI
cd /d "%~dp0"

REM Use the Python that has PySide6/pymupdf installed (verified miniconda env).
set "PY=C:\Users\Elin\miniconda3\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m app.main
if errorlevel 1 pause
