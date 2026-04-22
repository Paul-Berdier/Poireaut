"""Storage backends for the investigation graph.

Current:
  - InMemoryGraphStore: simple dict-based store for CLI use

Planned:
  - Neo4jStore: production graph DB
  - SqliteStore: persistent single-file
"""

from osint_core.storage.memory import InMemoryGraphStore

__all__ = ["InMemoryGraphStore"]
