"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.db.session import engine
from src.routes import (
    auth,
    connectors,
    datapoints,
    entities,
    health,
    identity,
    investigations,
    pivot,
    websocket,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Poireaut API",
    description="OSINT investigation platform — pivot, verify, weave the web.",
    version="0.6.0",
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
app.include_router(auth.router)
app.include_router(investigations.router)
app.include_router(entities.router)
app.include_router(datapoints.router)
app.include_router(pivot.router)
app.include_router(identity.router)
app.include_router(connectors.router)
app.include_router(websocket.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": "poireaut-api",
        "version": app.version,
        "status": "Mr. Poireaut is ready to investigate.",
    }
