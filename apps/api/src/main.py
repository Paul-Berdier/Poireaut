"""FastAPI application entrypoint.

Step 1 exposes only /health and /. Future steps will register routers here
(investigations, datapoints, connectors, websocket streaming, …).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.routes import health

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # TODO (step 2): initialise DB engine, run migrations, warm caches.
    yield
    # Shutdown
    # TODO (step 2): dispose DB engine, flush pending jobs.


app = FastAPI(
    title="Poireaut API",
    description="OSINT investigation platform — pivot, verify, weave the web.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": "poireaut-api",
        "version": app.version,
        "status": "Mr. Poireaut is ready to investigate.",
    }
