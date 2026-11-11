"""Async Redis client wrapper (cache/presence/pub-sub coordination)."""

from typing import Any

from redis.asyncio import Redis

# Single well-known channel for workspace realtime events (stage 7).
EVENTS_CHANNEL = "support_hub:events"


class RedisClient:
    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(redis_url, decode_responses=True)

    async def health_check(self) -> None:
        """Raise if Redis is unreachable (PING fails)."""
        await self._client.ping()

    async def publish_event(self, payload: str) -> None:
        """Fan out one realtime event to all connected workspace clients."""
        await self._client.publish(EVENTS_CHANNEL, payload)

    async def set_string(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def get_string(self, key: str) -> str | None:
        return await self._client.get(key)

    async def delete_key(self, key: str) -> None:
        await self._client.delete(key)

    def pubsub(self) -> Any:
        """Fresh pub/sub subscription for a WebSocket client (caller closes)."""
        return self._client.pubsub(ignore_subscribe_messages=True)

    async def close(self) -> None:
        await self._client.aclose()
