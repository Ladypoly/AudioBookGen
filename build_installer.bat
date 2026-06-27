@echo off
REM Build the Audio Drama Builder Windows installer (.exe).
REM Double-click this file, or run it from a terminal.
REM
REM Steps (see build/build_installer.ps1):
REM   1. build the React frontend
REM   2. freeze the Python sidecar with PyInstaller
REM   3. package an NSIS installer with electron-builder
REM Output: installer\Audio-Drama-Builder-Setup-<version>.exe

setlocal
cd /d "%~dp0"

REM Use a specific Python if ABG_PYTHON isn't already set (the verified env).
if not defined ABG_PYTHON set "ABG_PYTHON=C:\Users\Elin\miniconda3\python.exe"
if not exist "%ABG_PYTHON%" set "ABG_PYTHON=python"

echo Using Python: %ABG_PYTHON%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\build_installer.ps1"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Build finished. Installer is in:  "%~dp0installer"
) else (
    echo Build FAILED with exit code %RC%. See the messages above.
)
echo.
pause
endlocal
exit /b %RC%
