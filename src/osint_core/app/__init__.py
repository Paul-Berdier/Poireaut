"""Poireaut — desktop GUI application on top of osint_core.

Uses pywebview to render a native window around an HTML/CSS/JS UI,
with the Python investigation engine exposed via a JS bridge API.
"""

from osint_core.app.api import PoireautApi

__all__ = ["PoireautApi"]
