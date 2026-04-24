"""OSINT connectors package.

Each connector is a class derived from `BaseConnector` in `base.py`, registered
via the `@register` decorator from `registry.py`.

The registry is populated simply by importing the connector modules — Python
loads them and the decorator runs. Just add your connector to the list below.
"""
from src.connectors.base import BaseConnector, ConnectorResult, Finding
from src.connectors.registry import registry

# ─── Import each connector so its @register runs ──────────────
from src.connectors import holehe  # noqa: F401

__all__ = ["BaseConnector", "ConnectorResult", "Finding", "registry"]
