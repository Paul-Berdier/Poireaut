"""Celery tasks live here.

Step 1 ships a single `ping` task so you can verify the queue works:

    docker compose exec api python -c \
        "from celery import Celery; \
         c = Celery(broker='redis://redis:6379/1'); \
         print(c.send_task('src.tasks.ping').get(timeout=5))"

Step 3 will add the real OSINT connector tasks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.celery_app import celery


@celery.task(name="src.tasks.ping")
def ping() -> dict[str, str]:
    """Smoke-test task. Returns a timestamp + a bit of flavor."""
    return {
        "pong": "Mr. Poireaut tips his hat.",
        "at": datetime.now(timezone.utc).isoformat(),
    }
