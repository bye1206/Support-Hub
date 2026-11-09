"""Transactional outbox processing: lease -> dispatch -> processed/failed.

Delivery is at-least-once (AGENTS.md §6): a crash after lease re-delivers the
same idempotency_key later; consumers must dedup by that key. The default
handler only logs until stage 5 wires the real bot client.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent
from app.repositories.outbox import OutboxRepository
from app.services._tx import unit_of_work

logger = logging.getLogger(__name__)

# Exponential backoff: 2s, 4s, 8s... capped.
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 300.0
DEFAULT_LEASE_SECONDS = 30.0


def backoff_seconds(attempts: int) -> float:
    """Delay before the next attempt; `attempts` counts the failed tries so far."""
    return min(BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_MAX_SECONDS)


OutboxHandler = Callable[[OutboxEvent], Awaitable[None]]


class LoggingOutboxHandler:
    """Placeholder consumer: proves the pipeline until stage 5 replaces it."""

    async def __call__(self, event: OutboxEvent) -> None:
        logger.info(
            "Outbox event dispatched: type=%s key=%s aggregate=%s/%s",
            event.event_type,
            event.idempotency_key,
            event.aggregate_type,
            event.aggregate_id,
        )


class OutboxService:
    def __init__(
        self,
        repo: OutboxRepository | None = None,
        handler: OutboxHandler | None = None,
    ) -> None:
        self._repo = repo or OutboxRepository()
        self._handler = handler or LoggingOutboxHandler()

    async def register(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: Any | None,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> OutboxEvent | None:
        """Register inside the caller's transaction (atomic with the business
        change). Returns None when the idempotency key was already registered."""
        return await self._repo.register(
            session,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    async def process_batch(
        self,
        session: AsyncSession,
        *,
        batch_size: int = 10,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> int:
        """Lease pending events and dispatch them one by one.

        Each event's result is committed in its own transaction; `now` is
        injectable for deterministic backoff/crash-recovery tests.
        """
        current = now or datetime.now(UTC)
        async with unit_of_work(session):
            leased = await self._repo.lease(
                session, batch_size=batch_size, lease_seconds=lease_seconds, now=current
            )

        dispatched = 0
        for event in leased:
            try:
                await self._handler(event)
            except Exception as exc:
                logger.warning(
                    "Outbox dispatch failed: key=%s attempts=%s error=%s",
                    event.idempotency_key,
                    event.attempts,
                    type(exc).__name__,
                )
                async with unit_of_work(session):
                    await self._repo.mark_failed(
                        session,
                        event.id,
                        error=repr(exc),
                        retry_delay_seconds=backoff_seconds(event.attempts),
                        now=current,
                    )
            else:
                async with unit_of_work(session):
                    await self._repo.mark_processed(session, event.id, now=current)
                dispatched += 1
        return dispatched
