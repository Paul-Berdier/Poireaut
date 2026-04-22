"""Poireaut entry point — launches the desktop window."""

from __future__ import annotations

import logging
import sys
from importlib import resources
from pathlib import Path

from osint_core.app.api import PoireautApi


def _ui_html_path() -> str:
    """Return filesystem path to the UI index.html."""
    return str(resources.files("osint_core.app.ui").joinpath("index.html"))


def _icon_path() -> str | None:
    """Return filesystem path to the app icon best suited for this OS.

    Windows requires a real .ico file (System.Drawing.Icon refuses PNG).
    macOS & Linux are happy with PNG. If nothing suitable is found, we
    return None and the window uses pywebview's default icon.
    """
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates = ["icon.ico", "icon.png"]
    else:
        candidates = ["icon.png", "icon.ico"]

    for name in candidates:
        try:
            p = resources.files("osint_core.app.assets").joinpath(name)
            if Path(str(p)).is_file():
                return str(p)
        except Exception:
            continue
    return None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s · %(name)s · %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        import webview
    except ImportError:
        print(
            "\n× pywebview n'est pas installé.\n\n"
            "  Installez l'extra 'app' :\n\n"
            "    pip install 'osint-core[app]'\n\n"
            "  (ou : pip install pywebview)\n",
            file=sys.stderr,
        )
        return 1

    api = PoireautApi()
    icon = _icon_path()

    webview.create_window(
        title="Poireaut · Outil OSINT",
        url=_ui_html_path(),
        js_api=api,
        width=1320,
        height=840,
        min_size=(1040, 720),
        background_color="#f4ecd8",
        resizable=True,
        text_select=True,
    )

    # Try with the icon first; if anything about it fails (wrong format,
    # .NET complaining on Windows, old pywebview without `icon` kwarg),
    # retry without it — the window matters more than the icon.
    attempts: list[dict] = []
    if icon is not None:
        attempts.append({"debug": False, "icon": icon})
    attempts.append({"debug": False})

    last_exc: Exception | None = None
    for kwargs in attempts:
        try:
            webview.start(**kwargs)
            return 0
        except TypeError as exc:
            # `icon` not supported by this pywebview version
            last_exc = exc
            continue
        except Exception as exc:
            # Icon file rejected by the OS (e.g. Windows .NET wanting .ico),
            # or any other init error — retry without icon.
            last_exc = exc
            msg = str(exc)
            if "Icon" in msg or "picture" in msg or "icon" in kwargs:
                logging.warning(
                    "Échec d'initialisation avec l'icône (%s). "
                    "Relance sans icône.",
                    exc.__class__.__name__,
                )
                continue
            raise

    if last_exc is not None:
        raise last_exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
