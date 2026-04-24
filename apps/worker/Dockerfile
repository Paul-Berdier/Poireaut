# Poireaut Worker — Celery
# -------------------------------------------------------------------
# Multi-stage build:
#   1. `builder`: has gcc + Cairo headers + all Python build tools. Compiles
#      every wheel (pycairo among them, which maigret pulls in through
#      xhtml2pdf → svglib → rlpycairo). Wheels land under /wheels.
#   2. `runtime`: slim base image. Installs the pre-built wheels and runs
#      the worker. No gcc in the final image — ~150 MB lighter.
#
# The worker shares DB models + enums + schemas with the API. Rather than
# duplicate that code, we copy it from the sibling `api` package at build
# time. This requires the Docker build context to be the monorepo root.
# -------------------------------------------------------------------

# ────────── Stage 1: builder ──────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config \
    libcairo2-dev libpango1.0-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY apps/api/requirements.txt /build/api-req.txt
COPY apps/worker/requirements.txt /build/worker-req.txt

# Build wheels for every dependency. pip will compile from source when a
# wheel isn't available on PyPI (pycairo on 3.11-slim).
RUN pip wheel --wheel-dir /wheels -r api-req.txt -r worker-req.txt


# ────────── Stage 2: runtime ──────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime deps only — we need the *shared libraries* (not the -dev headers)
# that pycairo / lxml / Pillow dynamically link against.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Install pre-built wheels from the builder stage. No compilation here.
COPY --from=builder /wheels /wheels
COPY apps/api/requirements.txt /tmp/api-req.txt
COPY apps/worker/requirements.txt /tmp/worker-req.txt
RUN pip install --no-index --find-links=/wheels \
    -r /tmp/api-req.txt -r /tmp/worker-req.txt \
 && rm -rf /wheels

# ── Source: shared + worker-specific ─────────────────────────
# /app/src ends up with a merged tree:
#   src/db, src/models, src/config.py, src/schemas   ← from api
#   src/celery_app.py, src/tasks.py, src/connectors/ ← from worker
COPY apps/api/src ./src
COPY apps/worker/src ./src

CMD ["celery", "-A", "src.celery_app.celery", "worker", "--beat", "--scheduler", "celery.beat:PersistentScheduler", "--loglevel=info", "--concurrency=4"]
