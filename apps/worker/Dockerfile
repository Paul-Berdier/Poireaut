# Poireaut Worker — Celery
# -------------------------------------------------------------------
# The worker shares DB models + enums + schemas with the API.
# Rather than duplicate that code, we copy it from the sibling `api`
# package at build time. This requires the Docker build context to be
# the monorepo root (`.`), not `apps/worker`.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps — curl for healthchecks, git for any pip-from-git deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
 && rm -rf /var/lib/apt/lists/*

# ── Install worker + shared API deps ──────────────────────────
# API requirements are needed because we reuse its models & db layer.
COPY apps/api/requirements.txt /tmp/api-req.txt
COPY apps/worker/requirements.txt /tmp/worker-req.txt
RUN pip install -r /tmp/api-req.txt -r /tmp/worker-req.txt

# ── Source: shared + worker-specific ─────────────────────────
# /app/src ends up with a merged tree:
#   src/db, src/models, src/config.py, src/schemas   ← from api
#   src/celery_app.py, src/tasks.py, src/connectors/ ← from worker
COPY apps/api/src ./src
COPY apps/worker/src ./src

CMD ["celery", "-A", "src.celery_app.celery", "worker", "--beat", "--scheduler", "celery.beat:PersistentScheduler", "--loglevel=info", "--concurrency=4"]
