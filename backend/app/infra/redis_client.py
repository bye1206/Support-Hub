"""Async Redis client wrapper."""

from redis.asyncio import Redis


class RedisClient:
    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(redis_url, decode_responses=True)

    async def health_check(self) -> None:
        """Raise if Redis is unreachable (PING fails)."""
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()
