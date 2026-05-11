"""Auto-pivot orchestration.

The decision tree the worker walks for each new finding produced by a
pivot, to decide whether to chain another pivot on it automatically.

We deliberately keep the policy in one place (this module) so it's easy to
audit and tune. The orchestrator calls `should_auto_pivot(...)` for every
finding it just persisted; if the function says yes, the orchestrator
enqueues a fresh `run_connectors_for_datapoint` Celery task.

Two layers of safety:

1. **Per-finding decision** — confidence threshold, datatype eligibility,
   depth cap, deduplication, mode check.
2. **Circuit breakers** (`CircuitBreakerState`) — investigation-wide limits
   that NO user setting can override. If an enquête is creating datapoints
   faster than the investigator can review, we stop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.types import AutoPivotMode, DataType, VerificationStatus
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation

logger = logging.getLogger(__name__)


# ── Hard caps. Cannot be raised via settings — they exist to protect the
# database and the worker from runaway chains.
HARD_DEPTH_CAP = 10
HARD_TOTAL_AUTOCREATED_CAP = 500          # per investigation, lifetime
HARD_RECENT_AUTOCREATED_CAP = 200         # per investigation, last 60 minutes
HARD_AUTOCREATED_LOOKBACK = timedelta(minutes=60)

# Pivot-eligible data types. We deliberately exclude OTHER (free-form, often
# bios or stats — pivoting them is meaningless) and NAME (which has dozens
# of false positives in OSINT).
PIVOTABLE_TYPES: frozenset[DataType] = frozenset({
    DataType.EMAIL,
    DataType.USERNAME,
    DataType.PHONE,
    DataType.URL,
    DataType.ACCOUNT,
    DataType.DOMAIN,
    DataType.IP,
    DataType.PHOTO,
})


@dataclass
class AutoPivotDecision:
    """Why we did (or didn't) enqueue an auto-pivot for one finding."""
    enqueue: bool
    reason: str

    def __bool__(self) -> bool:
        return self.enqueue


async def should_auto_pivot(
    *,
    db: AsyncSession,
    investigation: Investigation,
    new_dp: DataPoint,
) -> AutoPivotDecision:
    """Return whether the orchestrator should chain another pivot on this DP.

    Pure function — no side effects, no DB writes. Caller is responsible
    for actually enqueuing the task if we say yes, and for stamping
    `auto_pivoted_at` on the source datapoint to make the decision
    idempotent on subsequent ticks.
    """
    # 1. Mode check ── If the investigation has auto-pivot disabled, stop here.
    mode = investigation.auto_pivot_mode
    if mode == AutoPivotMode.OFF:
        return AutoPivotDecision(False, "investigation.auto_pivot_mode=off")

    # MANUAL_ONLY mode never auto-pivots on freshly-created findings. The
    # API's PATCH /datapoints handler enqueues the pivot when the user
    # validates — bypassing this whole function.
    if mode == AutoPivotMode.MANUAL_ONLY:
        return AutoPivotDecision(
            False, "investigation.auto_pivot_mode=manual_only (user validation required)"
        )

    # 2. Type eligibility ── only pivotable types
    if new_dp.type not in PIVOTABLE_TYPES:
        return AutoPivotDecision(False, f"datatype {new_dp.type.value} not pivotable")

    # 3. Confidence threshold ── below threshold means we don't trust the
    #    new finding enough to act on it without human review.
    threshold = investigation.auto_pivot_min_confidence
    conf = new_dp.confidence
    if conf is None or conf < threshold:
        return AutoPivotDecision(
            False,
            f"confidence {conf if conf is not None else 'unknown'} < threshold {threshold:.2f}",
        )

    # 4. Depth cap ── effective cap is min(setting, hard cap)
    effective_cap = min(investigation.auto_pivot_max_depth, HARD_DEPTH_CAP)
    if new_dp.pivot_depth >= effective_cap:
        return AutoPivotDecision(
            False,
            f"pivot_depth {new_dp.pivot_depth} reached cap {effective_cap}",
        )

    # 5. Deduplication ── don't pivot if there's already an *identical* value
    #    being / about to be pivoted in this investigation. We check this
    #    by looking for any other datapoint with the same (entity_id, type,
    #    value) that has already been auto-pivoted.
    is_dup = await _has_already_pivoted_value(
        db, entity_id=new_dp.entity_id, dp_type=new_dp.type, value=new_dp.value,
        exclude_id=new_dp.id,
    )
    if is_dup:
        return AutoPivotDecision(
            False, f"value already pivoted in this investigation"
        )

    # 6. Investigation-wide circuit breakers
    breaker = await _check_circuit_breakers(db, investigation.id)
    if breaker is not None:
        return AutoPivotDecision(False, breaker)

    return AutoPivotDecision(True, "ok")


async def _has_already_pivoted_value(
    db: AsyncSession, *,
    entity_id, dp_type: DataType, value: str, exclude_id,
) -> bool:
    """True if another datapoint with the same value has been auto-pivoted."""
    stmt = (
        select(func.count(DataPoint.id))
        .where(
            DataPoint.entity_id == entity_id,
            DataPoint.type == dp_type,
            DataPoint.value == value,
            DataPoint.id != exclude_id,
            DataPoint.auto_pivoted_at.is_not(None),
        )
    )
    count = (await db.execute(stmt)).scalar_one()
    return count > 0


async def _check_circuit_breakers(
    db: AsyncSession, investigation_id,
) -> str | None:
    """Return None if all clear, else a human-readable reason to skip."""
    # Total lifetime auto-created datapoints in this investigation.
    # We count datapoints whose source_datapoint is non-null AND whose
    # source datapoint has been auto-pivoted (= they came from an auto chain).
    total_stmt = (
        select(func.count(DataPoint.id))
        .join(Entity, DataPoint.entity_id == Entity.id)
        .where(
            Entity.investigation_id == investigation_id,
            DataPoint.pivot_depth > 0,
        )
    )
    total = (await db.execute(total_stmt)).scalar_one() or 0
    if total >= HARD_TOTAL_AUTOCREATED_CAP:
        return (
            f"circuit breaker: {total} auto-created datapoints "
            f"reached lifetime cap of {HARD_TOTAL_AUTOCREATED_CAP}"
        )

    # Recent (last 60 minutes)
    cutoff = datetime.now(timezone.utc) - HARD_AUTOCREATED_LOOKBACK
    recent_stmt = (
        select(func.count(DataPoint.id))
        .join(Entity, DataPoint.entity_id == Entity.id)
        .where(
            Entity.investigation_id == investigation_id,
            DataPoint.pivot_depth > 0,
            DataPoint.created_at >= cutoff,
        )
    )
    recent = (await db.execute(recent_stmt)).scalar_one() or 0
    if recent >= HARD_RECENT_AUTOCREATED_CAP:
        return (
            f"circuit breaker: {recent} auto-created datapoints "
            f"in the last hour reached cap of {HARD_RECENT_AUTOCREATED_CAP}"
        )

    return None
