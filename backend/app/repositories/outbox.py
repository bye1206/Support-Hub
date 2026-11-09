"""Outbox lease/retry and inbound event dedup."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IntegrationEvent, IntegrationEventStatus, OutboxEvent, OutboxStatus


class OutboxRepository:
    async def register(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID | None,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> OutboxEvent | None:
        """Insert inside the caller's transaction; UNIQUE(idempotency_key) makes
        duplicate registration a no-op."""
        stmt = (
            pg_insert(OutboxEvent)
            .values(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(OutboxEvent)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def lease(
        self,
        session: AsyncSession,
        *,
        batch_size: int,
        lease_seconds: float,
        now: datetime,
    ) -> list[OutboxEvent]:
        """Claim pending rows (SKIP LOCKED): new rows, failed rows past their
        backoff, and rows whose previous lease expired (crash recovery)."""
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxStatus.NEW, OutboxStatus.PROCESSING]),
                OutboxEvent.next_attempt_at.is_(None)
                | (OutboxEvent.next_attempt_at <= now),
                OutboxEvent.lease_expires_at.is_(None)
                | (OutboxEvent.lease_expires_at <= now),
            )
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        leased = list((await session.scalars(stmt)).all())
        for event in leased:
            event.status = OutboxStatus.PROCESSING
            event.attempts += 1
            event.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await session.flush()
        return leased

    async def mark_processed(
        self, session: AsyncSession, event_id: uuid.UUID, *, now: datetime
    ) -> None:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.PROCESSED,
                processed_at=now,
                lease_expires_at=None,
                last_error=None,
            )
        )

    async def mark_failed(
        self,
        session: AsyncSession,
        event_id: uuid.UUID,
        *,
        error: str,
        retry_delay_seconds: float,
        now: datetime,
    ) -> None:
        """Release the lease and schedule a retry with backoff."""
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.NEW,
                lease_expires_at=None,
                last_error=error,
                next_attempt_at=now + timedelta(seconds=retry_delay_seconds),
            )
        )


class IntegrationEventRepository:
    async def register_if_absent(
        self,
        session: AsyncSession,
        *,
        source: str,
        external_event_id: str,
        payload: dict[str, Any] | None = None,
    ) -> IntegrationEvent | None:
        """Webhook idempotency: returns None when the event was seen before."""
        stmt = (
            pg_insert(IntegrationEvent)
            .values(
                source=source,
                external_event_id=external_event_id,
                payload=payload,
                status=IntegrationEventStatus.RECEIVED,
            )
            .on_conflict_do_nothing(
                index_elements=["source", "external_event_id"]
            )
            .returning(IntegrationEvent)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_processed(
        self, session: AsyncSession, event_id: uuid.UUID, *, now: datetime
    ) -> None:
        await session.execute(
            update(IntegrationEvent)
            .where(IntegrationEvent.id == event_id)
            .values(status=IntegrationEventStatus.PROCESSED, processed_at=now)
        )
