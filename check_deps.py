"""Diagnostic: check which optional extras are importable and why not."""

import sys
print(f"Python {sys.version}\n")

checks = [
    ("maigret",   "import maigret; print(f'  version: {maigret.__version__}')"),
    ("holehe",    "from holehe.core import import_submodules; print(f'  modules: {len(import_submodules(\"holehe.modules\"))}')"),
    ("imagehash", "import imagehash; print(f'  version: {imagehash.__version__}')"),
    ("PIL",       "from PIL import Image; print(f'  Pillow OK')"),
    ("pywebview", "import webview; print(f'  version: {webview.__version__}')"),
]

for name, test_code in checks:
    try:
        exec(test_code)
        print(f"  ✓ {name}\n")
    except ImportError as e:
        print(f"  ✗ {name} — {e}\n")
    except Exception as e:
        print(f"  ⚠ {name} — importable mais erreur: {e}\n")
