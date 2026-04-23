"""Poireaut — lance la fenêtre desktop.

Au démarrage, on assemble un HTML 100% autonome en mémoire :
  - CSS inliné dans <style>
  - JS inliné dans <script>
  - Images converties en base64 data URIs

Résultat : pywebview reçoit un seul blob HTML via `html=...`,
aucun fichier externe n'est référencé, aucun chemin relatif ne
peut casser (Windows, WebView2, n'importe quel environnement).
"""

from __future__ import annotations

import base64
import logging
import sys
from importlib import resources
from pathlib import Path

from osint_core.app.api import PoireautApi


def _read_text(package: str, filename: str) -> str:
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def _read_bytes(package: str, filename: str) -> bytes:
    return resources.files(package).joinpath(filename).read_bytes()


def _to_data_uri(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _icon_path() -> str | None:
    """Chemin absolu vers le .ico (Windows) ou .png (autres)."""
    ext = "icon.ico" if sys.platform == "win32" else "icon.png"
    try:
        p = resources.files("osint_core.app.assets").joinpath(ext)
        if Path(str(p)).is_file():
            return str(p)
    except Exception:
        pass
    try:
        alt = "icon.png" if sys.platform == "win32" else "icon.ico"
        p = resources.files("osint_core.app.assets").joinpath(alt)
        if Path(str(p)).is_file():
            return str(p)
    except Exception:
        pass
    return None


def _build_html() -> str:
    """Assemble le HTML final avec tout inliné."""
    html = _read_text("osint_core.app.ui", "index.html")
    css = _read_text("osint_core.app.ui", "styles.css")
    js = _read_text("osint_core.app.ui", "app.js")

    logo_uri = _to_data_uri(_read_bytes("osint_core.app.assets", "logo.png"))
    icon_uri = _to_data_uri(_read_bytes("osint_core.app.assets", "icon.png"))

    # Inliner CSS
    html = html.replace(
        '<link rel="stylesheet" href="./styles.css">',
        f"<style>\n{css}\n</style>",
    )

    # Inliner JS
    html = html.replace(
        '<script src="./app.js"></script>',
        f"<script>\n{js}\n</script>",
    )

    # Remplacer les images
    html = html.replace('href="./icon.png"', f'href="{icon_uri}"')
    html = html.replace('src="./icon.png"', f'src="{icon_uri}"')
    html = html.replace('src="./logo.png"', f'src="{logo_uri}"')

    return html


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
            "\n× pywebview n'est pas installé.\n"
            "  pip install pywebview\n",
            file=sys.stderr,
        )
        return 1

    api = PoireautApi()
    icon = _icon_path()

    try:
        html_blob = _build_html()
    except Exception as exc:
        logging.error("Échec de l'assemblage de l'interface : %s", exc)
        return 1

    window = webview.create_window(
        title="Poireaut · Outil OSINT",
        html=html_blob,
        js_api=api,
        width=1320,
        height=840,
        min_size=(1040, 720),
        background_color="#f4ecd8",
        resizable=True,
        text_select=True,
    )

    api.set_window(window)

    started = False
    if icon:
        try:
            webview.start(debug=False, icon=icon)
            started = True
        except Exception:
            pass
    if not started:
        try:
            webview.start(debug=False)
        except Exception as exc:
            logging.error("pywebview.start() a échoué : %s", exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
