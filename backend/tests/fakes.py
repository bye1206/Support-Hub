"""Fakes for unit tests: no network, no engine construction."""

from typing import Any


class FakeProbe:
    """Stands in for any infra client; may be told to raise."""

    def __init__(self, fail: bool = False, delay_seconds: float = 0.0) -> None:
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.closed = False
        self.calls = 0

    async def health_check(self) -> None:
        self.calls += 1
        if self.delay_seconds:
            import asyncio

            await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise ConnectionError("fake down")

    async def close(self) -> None:
        self.closed = True


def make_deps(
    db_fail: bool = False,
    redis_fail: bool = False,
) -> Any:
    """Build a Dependencies-like object with fake probes (runtime-typed)."""
    from app.infra.container import Dependencies

    return Dependencies(
        db=FakeProbe(db_fail),  # type: ignore[arg-type]
        redis=FakeProbe(redis_fail),  # type: ignore[arg-type]
    )
