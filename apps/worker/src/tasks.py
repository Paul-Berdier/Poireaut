"""Celery tasks.

Exposed tasks:

  src.tasks.ping                                 — smoke test
  src.tasks.run_connectors_for_datapoint(dp_id)  — pivot: run every compatible
                                                   connector against a datapoint
  src.tasks.run_single_connector(name, dp_id)    — run one specific connector

The orchestration task (`run_connectors_for_datapoint`) is the heart of the
pivot workflow:

  1. Load the source DataPoint from DB
  2. Ask the registry for every connector whose input_types ⊇ dp.type
  3. Spawn each connector concurrently via asyncio.gather
  4. Persist a ConnectorRun row per invocation (audit + health tracking)
  5. Insert each Finding as a new UNVERIFIED DataPoint pointing back at the
     source via `source_datapoint_id` (this is what the spider web renders)
  6. Publish a Redis pub/sub message on `investigation:{id}` so the API's
     WebSocket relay can push the update to the browser in real time
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.celery_app import celery
from src.config import get_settings
from src.connectors import registry
from src.connectors.base import Finding
from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
    RunStatus,
    VerificationStatus,
)
from src.models.connector import Connector, ConnectorRun
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Async DB session — scoped to the worker ────────────────────
# The API has its own engine. The worker runs in a Celery prefork pool,
# so the engine MUST be created inside each forked worker process — not
# at module-import time, otherwise asyncpg connections from the parent
# leak into children and break with "Future attached to a different loop"
# on every other task. We use NullPool: each task gets a fresh connection,
# closed at the end. ~10ms overhead, but no cross-loop hazard.
#
# The `worker_process_init` signal fires once when each forked worker
# starts; that's where we recreate the engine cleanly.

from celery.signals import worker_process_init
from sqlalchemy.pool import NullPool

_engine = None
_Session = None


def _make_engine_for_this_process():
    global _engine, _Session
    _engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,           # no pooled connections survive across tasks
        pool_pre_ping=False,
    )
    _Session = async_sessionmaker(_engine, expire_on_commit=False)


@worker_process_init.connect
def _on_worker_process_init(**_):
    """Recreate the async engine inside each forked worker."""
    _make_engine_for_this_process()


# Eager init for non-Celery contexts (unit tests, manual scripts):
# if no worker fork has happened yet, _Session is None, so first task call
# will build it lazily.
def _get_session():
    if _Session is None:
        _make_engine_for_this_process()
    return _Session


# ─── Redis client for pub/sub ──────────────────────────────────
_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _publish_investigation_event(investigation_id: uuid.UUID, event: dict[str, Any]) -> None:
    """Push an event to the channel the API's WebSocket relay subscribes to."""
    channel = f"investigation:{investigation_id}"
    try:
        _redis.publish(channel, json.dumps(event, default=str))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis publish failed: %s", exc)


# ─── Simple ping (step-1 sanity) ────────────────────────────────

@celery.task(name="src.tasks.ping")
def ping() -> dict[str, str]:
    return {
        "pong": "Mr. Poireaut tips his hat.",
        "at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Healthcheck task (scheduled via Celery Beat) ─────────────

@celery.task(name="src.tasks.healthcheck_all_connectors")
def healthcheck_all_connectors() -> dict[str, Any]:
    """Probe every registered connector and persist its health in DB.

    Runs daily via `celery beat`. Keeps the connectors table up to date
    so the Admin UI can show which tools are alive, and the orchestrator
    can skip dead ones in future versions.
    """
    return asyncio.run(_healthcheck_all())


async def _healthcheck_all() -> dict[str, Any]:
    from src.connectors import registry

    async with _get_session()() as db:
        connectors = registry.all()
        if not connectors:
            return {"checked": 0}

        # Ensure every connector has a row
        db_connectors = {c.name: c for c in await _sync_connectors_to_db(db, connectors)}
        await db.flush()

        summary: dict[str, str] = {}
        now = datetime.now(timezone.utc)
        for c in connectors:
            try:
                status = await asyncio.wait_for(c.healthcheck(), timeout=20)
            except asyncio.TimeoutError:
                status = HealthStatus.DEGRADED
            except Exception as exc:  # noqa: BLE001
                logger.exception("Healthcheck %s crashed: %s", c.name, exc)
                status = HealthStatus.DEAD

            row = db_connectors.get(c.name)
            if row is not None:
                row.health = status
                row.last_health_check = now
            summary[c.name] = status.value

        await db.commit()
        return {"checked": len(connectors), "status": summary, "at": now.isoformat()}


# ─── Main pivot task ────────────────────────────────────────────

@celery.task(name="src.tasks.run_connectors_for_datapoint", bind=True)
def run_connectors_for_datapoint(self, datapoint_id: str) -> dict[str, Any]:
    """Kick off every compatible connector against this datapoint.

    Runs asynchronously under asyncio via `asyncio.run`; Celery keeps the
    task itself sync so it plays nicely with its prefork pool.
    """
    return asyncio.run(_run_connectors_for_datapoint(uuid.UUID(datapoint_id)))


# ─── Targeted scrape (called from PATCH /datapoints when validating) ────

@celery.task(name="src.tasks.scrape_profile_for_datapoint")
def scrape_profile_for_datapoint(datapoint_id: str) -> dict[str, Any]:
    """Run the profile_scraper connector against one datapoint's source_url.

    Invoked automatically by the API when an investigator validates an
    account-or-URL datapoint with a usable source_url. This is what turns
    "you just validated @john on twitter" into "→ we pulled his name and
    avatar in the background".
    """
    return asyncio.run(_scrape_profile(uuid.UUID(datapoint_id)))


async def _scrape_profile(datapoint_id: uuid.UUID) -> dict[str, Any]:
    from src.connectors import registry

    async with _get_session()() as db:
        dp = await db.get(DataPoint, datapoint_id)
        if dp is None or not dp.source_url:
            return {"skipped": "no datapoint or no source_url"}

        scraper = registry.get("profile_scraper")
        if scraper is None:
            return {"skipped": "profile_scraper not registered"}

        # Ensure it has a DB row for FK purposes, same as the pivot task.
        db_connectors = {c.name: c for c in await _sync_connectors_to_db(db, [scraper])}
        await db.flush()
        db_connector = db_connectors[scraper.name]

        entity = await db.get(Entity, dp.entity_id)
        investigation_id = entity.investigation_id if entity else None

        if investigation_id is not None:
            _publish_investigation_event(
                investigation_id,
                {
                    "type": "pivot.started",
                    "investigation_id": str(investigation_id),
                    "datapoint_id": str(dp.id),
                    "connectors": ["profile_scraper"],
                    "reason": "auto-verify",
                },
            )

        try:
            result = await asyncio.wait_for(
                scraper.run(dp.source_url, DataType.URL),
                timeout=scraper.timeout_seconds,
            )
        except asyncio.TimeoutError:
            from src.connectors.base import ConnectorResult
            result = ConnectorResult(error="timeout")
        except Exception as exc:  # noqa: BLE001
            from src.connectors.base import ConnectorResult
            logger.exception("profile_scraper failed")
            result = ConnectorResult(error=f"{type(exc).__name__}: {exc}")

        now = datetime.now(timezone.utc)
        run = ConnectorRun(
            connector_id=db_connector.id,
            input_datapoint_id=dp.id,
            status=(RunStatus.SUCCESS if result.ok else RunStatus.FAILED),
            started_at=now,
            finished_at=now,
            duration_ms=None,
            result_count=len(result.findings),
            error_message=result.error,
            raw_output=result.raw_output,
        )
        db.add(run)

        for finding in result.findings:
            new_dp = _finding_to_datapoint(
                finding, dp, db_connector.id, depth=dp.pivot_depth + 1,
            )
            db.add(new_dp)
            if investigation_id is not None:
                await db.flush()
                _publish_investigation_event(
                    investigation_id,
                    {
                        "type": "datapoint.created",
                        "investigation_id": str(investigation_id),
                        "entity_id": str(dp.entity_id),
                        "datapoint": _datapoint_payload(new_dp),
                        "source_datapoint_id": str(dp.id),
                        "connector": "profile_scraper",
                    },
                )

        await db.commit()

        if investigation_id is not None:
            _publish_investigation_event(
                investigation_id,
                {
                    "type": "pivot.finished",
                    "investigation_id": str(investigation_id),
                    "datapoint_id": str(dp.id),
                    "findings_count": len(result.findings),
                    "connectors_run": 1,
                    "reason": "auto-verify",
                },
            )

        return {
            "datapoint_id": str(datapoint_id),
            "findings_count": len(result.findings),
            "error": result.error,
        }


async def _run_connectors_for_datapoint(datapoint_id: uuid.UUID) -> dict[str, Any]:
    async with _get_session()() as db:
        dp = await db.get(DataPoint, datapoint_id)
        if dp is None:
            return {"error": "datapoint not found", "datapoint_id": str(datapoint_id)}

        entity = await db.get(Entity, dp.entity_id)
        investigation_id = entity.investigation_id if entity else None

        # Load the investigation upfront — we need its auto_pivot settings
        # to drive the chaining decision after each finding lands.
        investigation = None
        if investigation_id is not None:
            investigation = await db.get(Investigation, investigation_id)

        connectors = registry.connectors_for(dp.type)
        if not connectors:
            logger.info("No connectors accept %s — nothing to do", dp.type)
            return {
                "datapoint_id": str(datapoint_id),
                "input_type": dp.type.value,
                "connectors_run": 0,
                "findings_count": 0,
            }

        # Stamp the source datapoint as "auto-pivoted now" — idempotency
        # marker. Even manual pivots set this, so the same datapoint can't
        # be picked up again as a fresh candidate by future cron sweeps.
        dp.auto_pivoted_at = datetime.now(timezone.utc)

        # Inject the investigation owner's API keys as env vars for the
        # duration of this task. Connectors continue to read os.getenv()
        # — no per-connector changes needed. We restore the original env
        # at the end so concurrent tasks for different users don't leak
        # into each other.
        env_override = await _load_user_api_keys_into_env(db, investigation)

        # Make sure every connector exists in the DB (upsert on first sight).
        db_connectors = {c.name: c for c in await _sync_connectors_to_db(db, connectors)}
        await db.flush()

        # Announce: pivot is starting.
        if investigation_id is not None:
            _publish_investigation_event(
                investigation_id,
                {
                    "type": "pivot.started",
                    "investigation_id": str(investigation_id),
                    "datapoint_id": str(dp.id),
                    "connectors": [c.name for c in connectors],
                    "depth": dp.pivot_depth,
                },
            )

        # Run every connector in parallel.
        coros = [_invoke_one(c.name, c, dp.value, dp.type) for c in connectors]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Children inherit depth = parent.depth + 1
        child_depth = dp.pivot_depth + 1

        total_findings = 0
        per_connector: list[dict[str, Any]] = []
        # Track auto-pivot enqueues to publish in pivot.finished
        chained: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for item in results:
            if isinstance(item, BaseException):
                logger.exception("Connector raised: %s", item)
                continue
            connector_name, result, duration_ms = item
            db_connector = db_connectors.get(connector_name)
            if db_connector is None:
                continue

            # Persist the run audit row
            run = ConnectorRun(
                connector_id=db_connector.id,
                input_datapoint_id=dp.id,
                status=(RunStatus.SUCCESS if result.ok else RunStatus.FAILED),
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                result_count=len(result.findings),
                error_message=result.error,
                raw_output=result.raw_output,
            )
            db.add(run)

            per_connector.append({
                "connector": connector_name,
                "findings_count": len(result.findings),
                "error": result.error,
                "duration_ms": duration_ms,
            })

            # Persist each finding, then ask the auto-pivot policy whether
            # to chain it.
            for finding in result.findings:
                new_dp = _finding_to_datapoint(
                    finding, dp, db_connector.id, depth=child_depth,
                )
                db.add(new_dp)
                total_findings += 1
                await db.flush()  # need new_dp.id for events + auto-pivot

                if investigation_id is not None:
                    _publish_investigation_event(
                        investigation_id,
                        {
                            "type": "datapoint.created",
                            "investigation_id": str(investigation_id),
                            "entity_id": str(dp.entity_id),
                            "datapoint": _datapoint_payload(new_dp),
                            "source_datapoint_id": str(dp.id),
                            "connector": connector_name,
                        },
                    )

                # ── Auto-pivot decision ──
                if investigation is not None:
                    from src._autopivot import should_auto_pivot
                    decision = await should_auto_pivot(
                        db=db, investigation=investigation, new_dp=new_dp,
                    )
                    if decision.enqueue:
                        # Send the chain task on its way. We use celery's
                        # send_task to avoid an import cycle on the task fn.
                        celery.send_task(
                            "src.tasks.run_connectors_for_datapoint",
                            args=[str(new_dp.id)],
                        )
                        chained.append({
                            "datapoint_id": str(new_dp.id),
                            "type": new_dp.type.value,
                            "value": new_dp.value[:80],
                            "confidence": new_dp.confidence,
                        })
                    else:
                        new_dp.auto_pivot_blocked_reason = decision.reason
                        skipped.append({
                            "datapoint_id": str(new_dp.id),
                            "reason": decision.reason,
                        })

        await db.commit()

        if investigation_id is not None:
            _publish_investigation_event(
                investigation_id,
                {
                    "type": "pivot.finished",
                    "investigation_id": str(investigation_id),
                    "datapoint_id": str(dp.id),
                    "findings_count": total_findings,
                    "connectors_run": len(connectors),
                    "depth": dp.pivot_depth,
                    "per_connector": per_connector,
                    # Auto-pivot summary so the UI can show "3 chained, 12 stopped"
                    "auto_pivot_chained": len(chained),
                    "auto_pivot_skipped": len(skipped),
                },
            )

        # Restore env vars to what they were before this task started
        _restore_env(env_override)

        return {
            "datapoint_id": str(datapoint_id),
            "input_type": dp.type.value,
            "connectors_run": len(connectors),
            "findings_count": total_findings,
            "auto_pivot_chained": len(chained),
            "auto_pivot_skipped": len(skipped),
        }


async def _load_user_api_keys_into_env(db, investigation) -> dict[str, str | None]:
    """Read the investigation owner's API keys from the DB and put them in
    os.environ for the duration of this task. Returns the original values
    so we can restore them via `_restore_env` at the end.

    No-op if no investigation (manual scrape outside a case) or no key
    rows exist for the owner.
    """
    import os
    from sqlalchemy import select

    if investigation is None:
        return {}
    try:
        from src.models.api_key import ApiKey  # local import — model lives in API package
    except ImportError:
        # The worker container may not ship the ApiKey model; bail out
        # quietly and let connectors fall back to env vars.
        return {}

    stmt = select(ApiKey).where(ApiKey.user_id == investigation.owner_id)
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return {}

    original: dict[str, str | None] = {}
    try:
        from src.services.api_keys import decrypt_value  # type: ignore
    except ImportError:
        return {}

    for row in rows:
        env_name = f"{row.connector_name.upper()}_API_KEY"
        env_alt = f"{row.connector_name.upper()}_API_TOKEN"
        try:
            plain = decrypt_value(row.encrypted_value)
        except Exception:  # noqa: BLE001
            continue
        original[env_name] = os.environ.get(env_name)
        original[env_alt] = os.environ.get(env_alt)
        os.environ[env_name] = plain
        os.environ[env_alt] = plain
    return original


def _restore_env(original: dict[str, str | None]) -> None:
    import os
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ─── Helpers ────────────────────────────────────────────────────

async def _invoke_one(
    name: str, connector, value: str, dtype: DataType
) -> tuple[str, Any, int]:
    """Run one connector with a hard timeout. Never raises."""
    from src.connectors.base import ConnectorResult

    started = datetime.now(timezone.utc)
    try:
        result = await asyncio.wait_for(
            connector.run(value, dtype),
            timeout=connector.timeout_seconds,
        )
    except asyncio.TimeoutError:
        result = ConnectorResult(error=f"Timeout after {connector.timeout_seconds}s")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Connector %s failed unexpectedly", name)
        result = ConnectorResult(error=f"{type(exc).__name__}: {exc}")

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return name, result, elapsed_ms


async def _sync_connectors_to_db(db: AsyncSession, connectors: list) -> list[Connector]:
    """Upsert the connectors into the DB so runs have a valid FK."""
    out: list[Connector] = []
    for c in connectors:
        stmt = select(Connector).where(Connector.name == c.name)
        db_row = (await db.execute(stmt)).scalar_one_or_none()
        if db_row is None:
            db_row = Connector(
                name=c.name,
                display_name=c.display_name,
                category=c.category,
                description=c.description or None,
                homepage_url=c.homepage_url,
                input_types=list(c.input_types),
                output_types=list(c.output_types),
                cost=c.cost,
                health=HealthStatus.UNKNOWN,
                enabled=True,
            )
            db.add(db_row)
        out.append(db_row)
    return out


def _finding_to_datapoint(
    finding: Finding, source_dp: DataPoint, connector_id: uuid.UUID,
    *, depth: int,
) -> DataPoint:
    return DataPoint(
        entity_id=source_dp.entity_id,
        type=finding.data_type,
        value=finding.value,
        status=VerificationStatus.UNVERIFIED,
        confidence=finding.confidence,
        source_connector_id=connector_id,
        source_datapoint_id=source_dp.id,
        source_url=finding.source_url,
        raw_data=finding.raw,
        extracted_at=finding.extracted_at,
        notes=finding.notes,
        pivot_depth=depth,
    )


def _datapoint_payload(dp: DataPoint) -> dict[str, Any]:
    """JSON-safe subset of DataPoint for pub/sub."""
    return {
        "id": str(dp.id),
        "entity_id": str(dp.entity_id),
        "type": dp.type.value,
        "value": dp.value,
        "status": dp.status.value,
        "confidence": dp.confidence,
        "source_url": dp.source_url,
        "notes": dp.notes,
        "extracted_at": dp.extracted_at.isoformat() if dp.extracted_at else None,
    }
