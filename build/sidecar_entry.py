"""PyInstaller entry point for the frozen sidecar.

Runs the FastAPI server (server.main.main). Kept tiny so the spec has a single,
stable script to analyse.
"""

from server.main import main

if __name__ == "__main__":
    main()
