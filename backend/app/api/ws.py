import asyncio
import contextlib

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.core.jwt import TokenError, decode_token
from app.db.session import async_session_factory
from app.models import Message, User
from app.models.enums import UserRole

router = APIRouter(tags=["ws"])


async def _authenticate(token: str | None) -> User | None:
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError:
        return None

    async with async_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.id == int(payload["sub"])))
        ).scalar_one_or_none()
        return user if user and user.is_active else None


async def _can_access_message(user: User, message_id: int) -> bool:
    async with async_session_factory() as session:
        query = select(Message.id).where(Message.id == message_id)
        if user.role != UserRole.admin:
            query = query.where(Message.user_id == user.id)
        result = (await session.execute(query)).scalar_one_or_none()
        return result is not None


@router.websocket("/ws/messages/{message_id}")
async def message_metrics_ws(websocket: WebSocket, message_id: int, token: str | None = None):
    user = await _authenticate(token)
    if user is None or not await _can_access_message(user, message_id):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    redis_client = aioredis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"message:{message_id}")

    async def relay():
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            await websocket.send_text(raw["data"].decode() if isinstance(raw["data"], bytes) else raw["data"])

    relay_task = asyncio.create_task(relay())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task
        await pubsub.unsubscribe(f"message:{message_id}")
        await pubsub.aclose()
        await redis_client.aclose()
