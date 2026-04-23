"""Celery application factory.

Exposes the `celery` instance so the worker can be started with:
    celery -A src.celery_app.celery worker --loglevel=info
"""
from __future__ import annotations

import os

from celery import Celery

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
    task_time_limit=600,        # 10 min hard limit per task
    task_soft_time_limit=540,   # 9 min soft limit (lets task clean up)
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
