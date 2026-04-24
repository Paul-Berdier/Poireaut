"""WebSocket route — streams investigation events to the browser in real time.

Client connects to  ws://…/ws/investigations/{id}?token=<JWT>
We auth (the browser WebSocket API can't set custom headers, so the token
comes as a query param — OK over WSS), verify ownership, then subscribe to
the Redis channel `investigation:{id}` and forward every message.

This is one-way: server → client. Clients don't send anything meaningful.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from src.config import get_settings
from src.db.session import AsyncSessionLocal
from src.models.investigation import Investigation
from src.models.user import User
from src.services.auth import TokenError, decode_access_token

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


async def _authenticate(token: str) -> User | None:
    """Decode the JWT and load the user, or return None."""
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, KeyError, ValueError):
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        return user


async def _owns_investigation(user: User, investigation_id: uuid.UUID) -> bool:
    async with AsyncSessionLocal() as db:
        inv = await db.get(Investigation, investigation_id)
        return inv is not None and inv.owner_id == user.id


@router.websocket("/ws/investigations/{investigation_id}")
async def investigation_stream(
    websocket: WebSocket,
    investigation_id: uuid.UUID,
    token: str = Query(..., description="JWT access token"),
) -> None:
    user = await _authenticate(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not await _owns_investigation(user, investigation_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    channel = f"investigation:{investigation_id}"
    await pubsub.subscribe(channel)

    await websocket.send_json(
        {"type": "hello", "investigation_id": str(investigation_id)}
    )

    try:
        # Loop until the client drops. On each Redis message we forward it.
        # We also listen for (and ignore) any client message so we notice
        # disconnects promptly.
        async def forward_redis() -> None:
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                # `data` is already a JSON string — send as text.
                await websocket.send_text(data)

        async def drain_client() -> None:
            while True:
                # We don't act on incoming messages but receive_text raises
                # WebSocketDisconnect when the client closes, which breaks
                # us out of the gather.
                await websocket.receive_text()

        await asyncio.gather(forward_redis(), drain_client())

    except WebSocketDisconnect:
        logger.info("WS client disconnected from %s", channel)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS relay error on %s: %s", channel, exc)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await redis_client.close()
        except Exception:  # noqa: BLE001
            pass
