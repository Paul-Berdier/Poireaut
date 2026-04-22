"""Collectors — plugins that discover or enrich entities.

Each collector declares what it `consumes` (entity types that trigger it)
and what it `produces` (entity types it can emit). The bus wires them
together automatically.
"""

from osint_core.collectors.base import BaseCollector

__all__ = ["BaseCollector"]
