"""Celery producer used by the API to enqueue worker tasks.

The API doesn't import worker code — it only produces messages onto the
broker. Tasks are identified by their name string, which the worker-side
task registers as.
"""
from __future__ import annotations

from celery import Celery

from src.config import get_settings

settings = get_settings()

celery = Celery(
    "poireaut-producer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


def enqueue_pivot(datapoint_id: str) -> str:
    """Send a `run_connectors_for_datapoint` task to the worker.

    Returns the task id so the caller can surface it (useful for polling
    or debugging).
    """
    result = celery.send_task(
        "src.tasks.run_connectors_for_datapoint",
        args=[datapoint_id],
    )
    return result.id
