"""Launcher for Poireaut — bypass the pip-generated .exe shim.

Some corporate antivirus setups block the small .exe wrappers that pip
creates in `.venv\\Scripts\\` (they look suspicious to heuristic scanners).
Run this script directly instead:

    python poireaut.py

It has the exact same effect as the `poireaut` console-script entry.
"""

from osint_core.app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
