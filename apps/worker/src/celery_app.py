"""Celery application factory.

Exposes the `celery` instance so the worker can be started with:
    celery -A src.celery_app.celery worker --loglevel=info

And the scheduler (for healthchecks) with:
    celery -A src.celery_app.celery beat --loglevel=info
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

celery = Celery(
    "poireaut",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["src.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Scheduled tasks — run by a separate `celery beat` process.
    beat_schedule={
        "healthcheck-all-connectors-daily": {
            "task": "src.tasks.healthcheck_all_connectors",
            # 04:17 UTC — once a day, off-peak and staggered off-the-hour.
            "schedule": crontab(hour="4", minute="17"),
        },
    },
)
