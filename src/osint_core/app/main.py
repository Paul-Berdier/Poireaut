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
    """Return filesystem path to the app icon, or None if unavailable."""
    try:
        p = resources.files("osint_core.app.assets").joinpath("icon.png")
        return str(p) if Path(str(p)).is_file() else None
    except Exception:
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

    window = webview.create_window(
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

    kwargs: dict = {"debug": False}
    if icon is not None:
        kwargs["icon"] = icon

    try:
        webview.start(**kwargs)
    except TypeError:
        # Older pywebview versions don't accept `icon`
        webview.start(debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
