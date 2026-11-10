"""Outbox/integration-event tests on real PostgreSQL: idempotency, lease,
retry with backoff, crash recovery, atomicity."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.integrations.tag.bot_client import TagDeliveryRejected
from app.integrations.tag.dispatch import RoutingOutboxHandler
from app.models import Message, MessageAuthorType, OutboxEvent, OutboxStatus
from app.repositories.messages import MessageRepository
from app.repositories.outbox import IntegrationEventRepository, OutboxRepository
from app.services.messages import MessageService
from app.services.outbox import LoggingOutboxHandler, OutboxService


async def _seed_events(session_factory, prefix: str, count: int) -> None:
    repo = OutboxRepository()
    async with session_factory() as session:
        for i in range(count):
            await repo.register(
                session,
                event_type="test.event",
                aggregate_type="test",
                aggregate_id=None,
                idempotency_key=f"{prefix}-{i}",
                payload={"index": i},
            )
        await session.commit()


@pytest.mark.anyio
async def test_outbound_event_dispatched_to_bot_and_processed(session_factory) -> None:
    """Full stage-5 path: message.outbound -> bot client -> PROCESSED."""
    repo = OutboxRepository()
    async with session_factory() as session:
        await repo.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=None,
            idempotency_key="outbound-1",
            payload={"message_id": "m-1", "conversation_id": "c-1", "text": "Привет"},
        )
        await session.commit()

    delivered: list[dict] = []

    class OkBot:
        async def send_message(self, payload: dict) -> None:
            delivered.append(payload)

    handler = RoutingOutboxHandler(bot=OkBot(), fallback=LoggingOutboxHandler())
    async with session_factory() as session:
        dispatched = await OutboxService(handler=handler).process_batch(session)
    assert dispatched == 1
    assert delivered == [{"message_id": "m-1", "conversation_id": "c-1", "text": "Привет"}]

    async with session_factory() as check:
        row = (await check.scalars(select(OutboxEvent))).one()
        assert row.status == OutboxStatus.PROCESSED


@pytest.mark.anyio
async def test_outbound_bot_failure_schedules_retry(session_factory) -> None:
    repo = OutboxRepository()
    async with session_factory() as session:
        await repo.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=None,
            idempotency_key="outbound-2",
            payload={"message_id": "m-2", "conversation_id": "c-2", "text": "…" },
        )
        await session.commit()

    class BrokenBot:
        async def send_message(self, payload: dict) -> None:
            raise TagDeliveryRejected("Bot answered HTTP 500")

    handler = RoutingOutboxHandler(bot=BrokenBot(), fallback=LoggingOutboxHandler())
    async with session_factory() as session:
        dispatched = await OutboxService(handler=handler).process_batch(session)
    assert dispatched == 0

    async with session_factory() as check:
        row = (await check.scalars(select(OutboxEvent))).one()
        assert row.status == OutboxStatus.NEW  # back to NEW, next_attempt scheduled
        assert row.attempts == 1
        assert row.next_attempt_at > datetime.now(UTC)
        assert "TagDeliveryRejected" in row.last_error


@pytest.mark.anyio
async def test_outbox_register_is_idempotent_by_key(session_factory) -> None:
    repo = OutboxRepository()
    async with session_factory() as session:
        first = await repo.register(
            session,
            event_type="t",
            aggregate_type="aggregate",
            aggregate_id=None,
            idempotency_key="k1",
            payload={},
        )
        duplicate = await repo.register(
            session,
            event_type="t",
            aggregate_type="aggregate",
            aggregate_id=None,
            idempotency_key="k1",
            payload={},
        )
        await session.commit()

    assert first is not None
    assert duplicate is None


@pytest.mark.anyio
async def test_integration_event_dedup(session_factory) -> None:
    """Webhook idempotency primitive: UNIQUE (source, external_event_id)."""
    repo = IntegrationEventRepository()
    async with session_factory() as session:
        first = await repo.register_if_absent(
            session, source="tag", external_event_id="evt-1", payload={"a": 1}
        )
        again = await repo.register_if_absent(session, source="tag", external_event_id="evt-1")
        await session.commit()

    assert first is not None
    assert again is None


@pytest.mark.anyio
async def test_concurrent_leases_are_disjoint(session_factory) -> None:
    """Two workers leasing simultaneously never take the same event."""
    await _seed_events(session_factory, "lease", 6)
    repo = OutboxRepository()

    async def lease() -> set[str]:
        async with session_factory() as session:
            # batch_size (3) < number of events (6) so BOTH workers get work.
            events = await repo.lease(
                session, batch_size=3, lease_seconds=30, now=datetime.now(UTC)
            )
            await session.commit()
            return {e.idempotency_key for e in events}

    keys1, keys2 = await asyncio.gather(lease(), lease())

    assert keys1 and keys2
    assert keys1.isdisjoint(keys2)
    assert keys1 | keys2 == {f"lease-{i}" for i in range(6)}


@pytest.mark.anyio
async def test_failed_event_retries_with_backoff(session_factory) -> None:
    await _seed_events(session_factory, "retry", 1)
    now = datetime.now(UTC)
    calls: list[str] = []

    def handler(fail: bool):
        async def call(event: OutboxEvent) -> None:
            calls.append(event.idempotency_key)
            if fail:
                raise RuntimeError("consumer down")

        return call

    failing = OutboxService(handler=handler(fail=True))
    async with session_factory() as session:
        assert await failing.process_batch(session, now=now) == 0

    async with session_factory() as check:
        event = (await check.scalars(select(OutboxEvent))).one()
        assert event.status == OutboxStatus.NEW
        assert event.attempts == 1
        assert event.next_attempt_at is not None and event.next_attempt_at > now
        assert event.last_error is not None

    # Still inside the backoff window: not leased.
    async with session_factory() as session:
        assert await failing.process_batch(session, now=now + timedelta(seconds=1)) == 0

    # Backoff passed: retried and succeeded (same key delivered twice).
    succeeding = OutboxService(handler=handler(fail=False))
    async with session_factory() as session:
        assert await succeeding.process_batch(session, now=now + timedelta(seconds=10)) == 1

    async with session_factory() as check:
        event = (await check.scalars(select(OutboxEvent))).one()
        assert event.status == OutboxStatus.PROCESSED
        assert event.processed_at is not None
    assert calls == ["retry-0", "retry-0"]


@pytest.mark.anyio
async def test_crash_after_lease_redelivers_once_lease_expires(session_factory) -> None:
    """Worker leased an event and crashed: redelivery after the lease expires."""
    await _seed_events(session_factory, "crash", 1)
    now = datetime.now(UTC)

    async with session_factory() as session:
        leased = await OutboxRepository().lease(
            session, batch_size=10, lease_seconds=30, now=now
        )
        await session.commit()
    assert len(leased) == 1

    seen: list[str] = []

    async def collect(event: OutboxEvent) -> None:
        seen.append(event.idempotency_key)

    service = OutboxService(handler=collect)

    async with session_factory() as session:
        assert await service.process_batch(session, now=now + timedelta(seconds=29)) == 0
    async with session_factory() as session:
        assert await service.process_batch(session, now=now + timedelta(seconds=31)) == 1

    assert seen == ["crash-0"]


@pytest.mark.anyio
async def test_message_and_outbox_roll_back_together(session_factory) -> None:
    """Criterion: message persist + outbox registration are atomic."""
    service = MessageService()
    async with session_factory() as session:
        await service.handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id="atomic-user",
            text="первое",
        )

    with pytest.raises(RuntimeError):
        async with session_factory() as session, session.begin():
            repo = OutboxRepository()
            await repo.register(
                session,
                event_type="message.outbound",
                aggregate_type="message",
                aggregate_id=None,
                idempotency_key="doomed-event",
                payload={},
            )
            conversation = (
                await session.scalars(
                    select(Message.conversation_id).limit(1)
                )
            ).first()
            assert conversation is not None
            await MessageRepository().create(
                session,
                conversation_id=conversation,
                sequence_no=99,
                author_type=MessageAuthorType.SYSTEM,
                text="will roll back",
            )
            raise RuntimeError("simulated failure after both writes")

    async with session_factory() as check:
        outbox_count = await check.scalar(select(func.count()).select_from(OutboxEvent))
        message_count = await check.scalar(select(func.count()).select_from(Message))
    assert outbox_count == 1  # only the seeded event
    assert message_count == 1  # only the seeded message
