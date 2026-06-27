# Build the Audio Drama Builder Windows installer end-to-end.
#
#   1. Build the React frontend           -> frontend/dist
#   2. Freeze the Python sidecar (PyInstaller) -> dist_sidecar/abg-sidecar
#   3. Package with electron-builder (NSIS) -> installer/Audio-Drama-Builder-Setup-*.exe
#
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File build/build_installer.ps1
#
# Requirements:
#   - Node + npm, Python (with: pip install -r requirements.txt pyinstaller)
#   - electron/ffmpeg/ffmpeg.exe present (see electron/ffmpeg/README.md)
#   - Set $env:ABG_PYTHON to a specific python.exe if not on PATH.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = if ($env:ABG_PYTHON) { $env:ABG_PYTHON } else { "python" }

# Native commands don't throw on non-zero exit in PowerShell — check explicitly.
function CheckExit([string]$what) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "BUILD FAILED at: $what (exit code $LASTEXITCODE)" -ForegroundColor Red
        Set-Location $root
        exit 1
    }
}

# 0. Bump version -----------------------------------------------------------
# Each build bumps the patch version in electron/package.json so every
# installer gets a unique name/version (AudioBookGen-Setup-<version>.exe).
Write-Host "==> [0/3] Bumping version..." -ForegroundColor Cyan
Set-Location (Join-Path $root "electron")
npm version patch --no-git-tag-version --allow-same-version | Out-Null
CheckExit "version bump"
$ver = (Get-Content package.json -Raw | ConvertFrom-Json).version
Write-Host "    Version is now $ver"
Set-Location $root

# 1. Frontend ----------------------------------------------------------------
Write-Host "==> [1/3] Building frontend..." -ForegroundColor Cyan
# cd into the folder so `npm run` resolves the LOCAL node_modules/.bin
# (npm --prefix does NOT do this reliably and also spams root package.json errors).
Set-Location (Join-Path $root "frontend")
npm install;   CheckExit "frontend: npm install"
npm run build; CheckExit "frontend: vite build"

# 2. Python sidecar ----------------------------------------------------------
Write-Host "==> [2/3] Freezing Python sidecar (PyInstaller)..." -ForegroundColor Cyan
Set-Location $root
& $py -m PyInstaller --noconfirm --distpath dist_sidecar --workpath build/_work build/sidecar.spec
CheckExit "PyInstaller freeze"

# 3. Installer ---------------------------------------------------------------
Write-Host "==> [3/3] Packaging installer (electron-builder)..." -ForegroundColor Cyan
Set-Location (Join-Path $root "electron")
Write-Host "    Installing electron + electron-builder (first run downloads ~200MB)..."
npm install;       CheckExit "electron: npm install"
npm run installer; CheckExit "electron-builder (NSIS)"

# Verify the installer actually exists ---------------------------------------
Set-Location $root
$exe = Get-ChildItem (Join-Path $root "installer") -Filter "*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($exe) {
    Write-Host ""
    Write-Host "Done. Installer: $($exe.FullName)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "BUILD FAILED: electron-builder finished but no .exe is in '$root\installer'." -ForegroundColor Red
    exit 1
}
