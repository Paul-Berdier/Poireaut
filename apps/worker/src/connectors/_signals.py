"""Composable confidence signals.

Every connector that produces a Finding now ships a list of named, signed
"signals" instead of a magic float. The combiner turns those into a final
confidence number — and we keep the raw signal list around in
`Finding.raw_data` so the UI can show *why* a score is what it is.

A signal is just `(name, weight, reason)` where:
  - `name` is a short stable identifier (snake_case)
  - `weight` is a float; positive moves confidence up, negative moves it down
  - `reason` is a short human-readable French phrase shown in the UI

By convention, the FIRST signal is the connector's "base prior" — what
the connector starts with before any evidence is taken into account.

The combiner formula is intentionally simple: sum all weights, then clamp
to [0.05, 0.97]. Simpler than a Bayesian product, more predictable when
debugging, and good enough for the OSINT confidence levels we care about
(low / medium / high). A future iteration could go fancier if needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Hard floor/ceiling — we never claim 100% certainty because OSINT signals
# are always probabilistic, and we never go below 5% because if a finding
# made it through the pipeline at all there is *some* evidence.
MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 0.97


@dataclass
class Signal:
    name: str
    weight: float
    reason: str


@dataclass
class ConfidenceBuild:
    """Accumulator a connector uses to compose its score for one finding."""
    signals: list[Signal] = field(default_factory=list)

    def add(self, name: str, weight: float, reason: str) -> None:
        self.signals.append(Signal(name=name, weight=weight, reason=reason))

    def compose(self) -> float:
        """Sum all weights, clamp to the allowed range."""
        total = sum(s.weight for s in self.signals)
        return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, total))

    def to_raw(self) -> list[dict]:
        """Serialize signals for storage in datapoint.raw_data."""
        return [
            {"name": s.name, "weight": round(s.weight, 3), "reason": s.reason}
            for s in self.signals
        ]


def build(base_name: str, base_weight: float, base_reason: str) -> ConfidenceBuild:
    """Start a new confidence build with a base prior signal."""
    b = ConfidenceBuild()
    b.add(base_name, base_weight, base_reason)
    return b
