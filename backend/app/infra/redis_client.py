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

    def pubsub(self) -> Any:
        """Fresh pub/sub subscription for a WebSocket client (caller closes)."""
        return self._client.pubsub(ignore_subscribe_messages=True)

    async def close(self) -> None:
        await self._client.aclose()
