"""Base class every OSINT connector inherits from.

A connector is a thin adapter between an external tool / API and Poireaut's
normalized `DataPoint` model. It has four responsibilities:

  1. Declare its metadata (name, category, cost, input/output types).
  2. Run — given an input DataPoint, produce zero or more `Finding`s.
  3. Health-check itself on demand — we use this to auto-disable dead tools.
  4. Handle its own errors gracefully — a connector that raises is buggy;
     a connector that can't find anything returns an empty list.

Connectors run inside a Celery task in the worker process. They must be
async because most of them are I/O-bound (HTTP requests). The orchestrator
runs many connectors in parallel via `asyncio.gather`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
)


# ─── Data types exchanged with the orchestrator ─────────────────

@dataclass
class Finding:
    """A single piece of information discovered by a connector.

    Multiple findings can be produced from one run (e.g. Maigret finds 30
    accounts for one username → 30 findings). Each becomes one DataPoint.
    """

    data_type: DataType
    value: str

    # Confidence in [0, 1]. None means "don't know" and is treated as 0.5
    # by the UI when displaying a color scale.
    confidence: float | None = None

    # Where the connector got this from — URL to the original record, if any.
    source_url: str | None = None

    # When the underlying source was last updated (best-effort — not all
    # connectors provide this). UI shows this as "data from X days ago".
    extracted_at: datetime | None = None

    # Free-form raw payload. Stored in DataPoint.raw_data for debugging
    # and future re-processing without re-querying the source.
    raw: dict[str, Any] | None = None

    # Optional notes the connector wants the investigator to see.
    notes: str | None = None


@dataclass
class ConnectorResult:
    """Full outcome of a single connector run."""

    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    raw_output: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ─── The base class itself ──────────────────────────────────────

class BaseConnector(ABC):
    """Abstract parent of every connector.

    Subclasses set the `ClassVar` attributes below and implement `run()`.
    `healthcheck()` has a sensible default but may be overridden.
    """

    # ── Metadata ──
    name: ClassVar[str]                     # stable id, e.g. "holehe"
    display_name: ClassVar[str]             # pretty, e.g. "Holehe — email accounts"
    category: ClassVar[ConnectorCategory]
    description: ClassVar[str] = ""
    homepage_url: ClassVar[str | None] = None
    cost: ClassVar[ConnectorCost] = ConnectorCost.FREE

    # Which DataType kinds this connector accepts as input / produces as output.
    # Used by the orchestrator to pick connectors that match a pivot.
    input_types: ClassVar[set[DataType]]
    output_types: ClassVar[set[DataType]]

    # Timeouts — enforced by the orchestrator via asyncio.wait_for.
    timeout_seconds: ClassVar[int] = 60

    # ── Required API ──

    @abstractmethod
    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        """Execute the connector against one input value.

        Must never raise for expected error cases (network down, API 4xx,
        rate limits). Catch those and return `ConnectorResult(error="…")`.
        The orchestrator catches unexpected raises too, but clean handling
        gives better error messages.
        """

    # ── Optional hooks ──

    async def healthcheck(self) -> HealthStatus:
        """Verify the tool is still reachable.

        Default implementation: call `run()` with a known-safe value. Override
        for connectors where a smarter probe is cheaper.
        """
        try:
            probe = self._healthcheck_probe()
            if probe is None:
                return HealthStatus.UNKNOWN
            result = await self.run(probe[0], probe[1])
            return HealthStatus.OK if result.ok else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD

    def _healthcheck_probe(self) -> tuple[str, DataType] | None:
        """Return a safe (value, type) pair for the default healthcheck.

        Returning None means "skip default probe" — useful for paid connectors
        where you don't want to burn quota on health checks.
        """
        return None

    # ── Helpers ──

    @classmethod
    def accepts(cls, data_type: DataType) -> bool:
        return data_type in cls.input_types

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.name}>"


def now_utc() -> datetime:
    """Small helper so connectors don't have to import datetime everywhere."""
    return datetime.now(timezone.utc)
