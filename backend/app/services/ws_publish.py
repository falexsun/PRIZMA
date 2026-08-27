import json

import redis

from app.core.config import settings

_redis_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url)
    return _redis_client


def publish_message_update(message_id: int, user_id: int, payload: dict) -> None:
    client = _get_client()
    data = json.dumps(payload)
    client.publish(f"message:{message_id}", data)
    client.publish(f"user:{user_id}", data)
