# PyInstaller spec for the AudioBookGen FastAPI sidecar.
#
# Freezes server.main (which imports the whole app/services pipeline) into a
# standalone onedir app, so the installed app needs no system Python.
#
# Build:  pyinstaller build/sidecar.spec   (run from the repo root)
# Output: dist_sidecar/abg-sidecar/abg-sidecar.exe
#
# Read-only assets (prompts/, workflows/) are NOT bundled here — the Electron
# shell ships them as resources and points ABG_ASSET_ROOT at them. User data
# (projects/, settings.json) goes to a per-user folder via ABG_DATA_ROOT.

from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

# Lazy imports inside app/services (pydub, fitz, ebooklib, …) are easy to miss
# by static analysis, so pull every submodule of our own packages in explicitly.
hiddenimports = []
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("server")
hiddenimports += [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
]

datas = []
binaries = []

# Packages that load their own data files / have C extensions.
for pkg in ("ebooklib", "fitz", "docx", "bs4", "PIL", "mutagen", "pydantic"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["sidecar_entry.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # The sidecar is a thin FastAPI server that drives ComfyUI/Ollama over HTTP.
    # It must NOT bundle the heavy ML stack (that lives inside ComfyUI) — those
    # get pulled in transitively (torch alone is ~4.6 GB) and blow the NSIS 2 GB
    # mmap limit. Optional voice-optimize deps import these lazily and degrade
    # gracefully when absent, so excluding them is safe.
    excludes=[
        "PySide6", "shiboken6", "tkinter",
        "torch", "torchaudio", "torchvision", "torchgen", "functorch",
        "transformers", "tokenizers", "accelerate", "safetensors",
        "bitsandbytes", "triton", "xformers",
        "numba", "llvmlite",
        "cv2",
        "scipy", "sklearn",
        "pandas", "polars", "pyarrow",
        "matplotlib",
        "av",
        "imageio", "imageio_ffmpeg",
        "sympy", "tensorflow", "cupy", "onnxruntime",
        "pygame", "yt_dlp",
        "demucs", "deepfilternet", "voicefixer", "speechbrain",
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="abg-sidecar",
    console=False,       # no console window when launched by the Electron shell
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="abg-sidecar",
)
