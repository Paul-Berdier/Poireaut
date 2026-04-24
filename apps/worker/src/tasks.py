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

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Async DB session — scoped to the worker ────────────────────
# The API has its own engine (src/db/session.py). The worker runs in a
# different process, so we create our own to avoid sharing connections
# across process boundaries.

_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=5,
)
_Session = async_sessionmaker(_engine, expire_on_commit=False)


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

    async with _Session() as db:
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


async def _run_connectors_for_datapoint(datapoint_id: uuid.UUID) -> dict[str, Any]:
    async with _Session() as db:
        dp = await db.get(DataPoint, datapoint_id)
        if dp is None:
            return {"error": "datapoint not found", "datapoint_id": str(datapoint_id)}

        entity = await db.get(Entity, dp.entity_id)
        investigation_id = entity.investigation_id if entity else None

        connectors = registry.connectors_for(dp.type)
        if not connectors:
            logger.info("No connectors accept %s — nothing to do", dp.type)
            return {
                "datapoint_id": str(datapoint_id),
                "input_type": dp.type.value,
                "connectors_run": 0,
                "findings_count": 0,
            }

        # Make sure every connector exists in the DB (upsert on first sight).
        db_connectors = {c.name: c for c in await _sync_connectors_to_db(db, connectors)}
        await db.flush()

        # Run every connector in parallel. Each returns (connector_name, ConnectorResult).
        coros = [
            _invoke_one(c.name, c, dp.value, dp.type)
            for c in connectors
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        total_findings = 0
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
                started_at=datetime.now(timezone.utc),  # approx — we don't track precisely
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                result_count=len(result.findings),
                error_message=result.error,
                raw_output=result.raw_output,
            )
            db.add(run)

            # Persist each finding as a new DataPoint, pointing back at the source
            for finding in result.findings:
                new_dp = _finding_to_datapoint(finding, dp, db_connector.id)
                db.add(new_dp)
                total_findings += 1

                if investigation_id is not None:
                    # We flush so new_dp.id is available before publishing
                    await db.flush()
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

        await db.commit()

        return {
            "datapoint_id": str(datapoint_id),
            "input_type": dp.type.value,
            "connectors_run": len(connectors),
            "findings_count": total_findings,
        }


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
    finding: Finding, source_dp: DataPoint, connector_id: uuid.UUID
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
