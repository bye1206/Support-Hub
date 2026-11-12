"""Integration tests of the ingress/lifecycle flows on real PostgreSQL."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.exceptions import StateConflict
from app.models import (
    AuditLog,
    Conversation,
    ConversationSession,
    DialogMode,
    Message,
    MessageAuthorType,
    OutboxEvent,
    SessionStatus,
    Ticket,
    TicketStatus,
)
from app.repositories.conversations import SessionRepository
from app.services.messages import MessageService
from app.services.sessions import SESSION_DURATION, SessionService
from app.services.tickets import TicketService

INGRESS = dict(
    channel_type="tag",
    external_user_id="tag-user-1",
    external_user_name="Ivan Petrov",
)


def ingress_kwargs(**overrides: object) -> dict:
    kwargs = dict(INGRESS)
    kwargs.update(overrides)
    return kwargs


@pytest.mark.anyio
async def test_first_message_creates_full_chain(session_factory) -> None:
    async with session_factory() as session:
        result = await MessageService().handle_incoming_user_message(
            session,
            **ingress_kwargs(text="Не работает вход", external_post_id="post-1"),
        )

        # P-06: user auto-provisioned with the channel identity.
        assert result.message.author_user_id is not None
        # D-039: the first message puts the ticket into "Обработка ИИ".
        assert result.ticket.status == TicketStatus.AI_PROCESSING
        assert result.conversation.mode == DialogMode.AI_ACTIVE
        assert result.conversation_created is True
        # D-007: exactly 3 hours.
        assert result.session.expires_at - result.session.started_at == SESSION_DURATION
        assert result.message.sequence_no == 1

        outbox = list((await session.scalars(select(OutboxEvent))).all())
        assert [e.event_type for e in outbox] == ["message.user_received"]

        audit_actions = set(
            (await session.scalars(select(AuditLog.action))).all()
        )
        assert {"ticket.created", "message.created"} <= audit_actions


@pytest.mark.anyio
async def test_duplicate_post_id_does_not_create_second_message(session_factory) -> None:
    service = MessageService()
    async with session_factory() as first_session:
        first = await service.handle_incoming_user_message(
            first_session,
            **ingress_kwargs(text="Первый раз", external_post_id="post-dup"),
        )

    async with session_factory() as second_session:
        second = await service.handle_incoming_user_message(
            second_session,
            **ingress_kwargs(text="Повторная доставка", external_post_id="post-dup"),
        )

    assert second.deduplicated is True
    assert second.message.id == first.message.id

    async with session_factory() as check:
        assert len(list((await check.scalars(select(Message))).all())) == 1
        assert len(list((await check.scalars(select(OutboxEvent))).all())) == 1
        assert len(list((await check.scalars(select(Ticket))).all())) == 1


@pytest.mark.anyio
async def test_ai_reply_opens_new_ticket(session_factory) -> None:
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Вопрос к ИИ")
        )
        conversation_id, ticket_id = first.conversation.id, first.ticket.id

    async with session_factory() as session:
        reply = await service.add_ai_reply(
            session, conversation_id=conversation_id, text="Ответ ИИ"
        )

    assert reply.ticket.id == ticket_id
    assert reply.ticket.status == TicketStatus.OPEN  # D-039: processing done
    assert reply.message.sequence_no == 2
    assert reply.message.author_type == MessageAuthorType.AI

    async with session_factory() as check:
        events = list((await check.scalars(select(OutboxEvent.event_type))).all())
    assert events == ["message.user_received", "message.outbound"]


@pytest.mark.anyio
async def test_operator_reply_pends_user_and_takes_over_dialog(session_factory) -> None:
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Нужен человек")
        )
        ticket_id = first.ticket.id

    async with session_factory() as session:
        reply = await service.add_operator_reply(
            session, ticket_id=ticket_id, text="Здравствуйте, я оператор"
        )

    # D-011: straight to PENDING_USER; dialog in human mode.
    assert reply.ticket.status == TicketStatus.PENDING_USER
    assert reply.conversation.mode == DialogMode.HUMAN_ACTIVE
    assert reply.message.sequence_no == 2

    # User's next message returns the ticket to OPEN (docs/01 §5).
    async with session_factory() as session:
        follow_up = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Вот скриншот")
        )
    assert follow_up.ticket.status == TicketStatus.OPEN
    assert follow_up.message.sequence_no == 3


@pytest.mark.anyio
async def test_resolve_then_user_message_starts_new_ticket(session_factory) -> None:
    """D-010 revised: a resolved ticket is terminal — the user's next message
    creates a NEW ticket in a NEW dialog; no reopen exists."""
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Проблема")
        )
        ticket_id, old_conversation_id = first.ticket.id, first.conversation.id

    async with session_factory() as session:
        await TicketService().resolve(session, ticket_id)

    async with session_factory() as session:
        again = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Опять сломалось")
        )

    assert again.ticket_reopened is False
    assert again.ticket.id != ticket_id
    assert again.conversation.id != old_conversation_id
    assert again.conversation_created is True


@pytest.mark.anyio
async def test_close_then_new_message_starts_new_ticket_and_dialog(
    session_factory,
) -> None:
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Проблема №1")
        )
        ticket_id, old_conversation_id = first.ticket.id, first.conversation.id

    async with session_factory() as session:
        await TicketService().close(session, ticket_id)

    async with session_factory() as session:
        second = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Новая проблема")
        )

    assert second.ticket.id != ticket_id
    assert second.conversation.id != old_conversation_id
    assert second.conversation_created is True
    assert second.ticket.status == TicketStatus.AI_PROCESSING
    assert second.message.sequence_no == 1  # numbering restarts in the new dialog

    # The old dialog is closed with its sessions ENDED.
    async with session_factory() as check:
        old_conversation = await check.get(Conversation, old_conversation_id)
        assert old_conversation is not None
        assert old_conversation.mode == DialogMode.CLOSED
        sessions = list(
            (
                await check.scalars(
                    select(ConversationSession).where(
                        ConversationSession.conversation_id == old_conversation_id
                    )
                )
            ).all()
        )
        assert {s.status for s in sessions} == {SessionStatus.ENDED}


@pytest.mark.anyio
async def test_concurrent_messages_in_one_dialog_get_distinct_sequences(
    session_factory,
) -> None:
    """Two simultaneous user messages: no duplicates, one ticket, retry wins."""
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Первое")
        )
        conversation_id = first.conversation.id
        ticket_id = first.ticket.id

    async def send(text_value: str) -> None:
        async with session_factory() as session:
            await service.handle_incoming_user_message(
                session,
                channel_type="tag",
                external_user_id=INGRESS["external_user_id"],
                text=text_value,
            )

    # Both live messages observe the same state_version; the optimistic-lock
    # loser must retry the FSM transition instead of failing (D-039 flow).
    await asyncio.gather(send("Второе"), send("Третье"))

    async with session_factory() as check:
        sequences = list(
            (
                await check.scalars(
                    select(Message.sequence_no).where(
                        Message.conversation_id == conversation_id
                    )
                )
            ).all()
        )
        ticket = await check.get(Ticket, ticket_id)
        assert ticket is not None
        assert sorted(sequences) == [1, 2, 3]
        assert ticket.status == TicketStatus.AI_PROCESSING  # D-039, both raced here
        assert ticket.state_version == 2


@pytest.mark.anyio
async def test_optimistic_conflict_on_simultaneous_resolve(session_factory) -> None:
    service = MessageService()
    async with session_factory() as session:
        first = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Конфликтный тикет")
        )
        ticket_id = first.ticket.id

    async with session_factory() as loser, session_factory() as winner:
        # Both load version 1, then the winner commits first. The loser keeps
        # a strong reference: the identity map is weak, so a discarded result
        # would be GC'd and session.get would re-fetch the winner's committed
        # state instead of raising the optimistic-lock conflict.
        loser_ticket = await loser.get(Ticket, ticket_id)
        stale_version = loser_ticket.state_version
        await winner.get(Ticket, ticket_id)
        await TicketService().resolve(winner, ticket_id)

        with pytest.raises(StateConflict):
            await TicketService().resolve(loser, ticket_id)

    assert stale_version == 2  # both loaded after the first message (v1 -> v2)


@pytest.mark.anyio
async def test_expired_session_is_replaced_lazily(session_factory) -> None:
    conversation_id, _ = await _seed_conversation(session_factory, "user-expired-1")

    # Age the ACTIVE session into the past (expires_at = started_at + 3h holds).
    await _expire_seed_session(session_factory, conversation_id)

    async with session_factory() as session:
        fresh = await SessionService().ensure_active(session, conversation_id)

    assert fresh.expires_at - fresh.started_at == SESSION_DURATION
    assert fresh.expires_at > datetime.now(UTC)


@pytest.mark.anyio
async def test_worker_expires_due_sessions_only(session_factory) -> None:
    from app.worker.tasks import expire_sessions

    conversation_id, _ = await _seed_conversation(session_factory, "user-expired-2")
    other_id, _ = await _seed_conversation(session_factory, "user-fresh-2")

    # The first dialog's session started 4 hours ago; the second is fresh.
    await _expire_seed_session(session_factory, conversation_id)

    expired = await expire_sessions({"session_factory": session_factory})

    assert expired == 1
    async with session_factory() as check:
        statuses = dict(
            (
                await check.execute(
                    select(
                        ConversationSession.conversation_id,
                        ConversationSession.status,
                    )
                )
            ).all()
        )
    assert statuses[conversation_id] == SessionStatus.EXPIRED
    assert statuses[other_id] == SessionStatus.ACTIVE


async def _seed_conversation(
    session_factory, external_user_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        result = await MessageService().handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=external_user_id,
            text="seed",
        )
        conversation_id, user_id = result.conversation.id, result.message.author_user_id
    assert user_id is not None
    return conversation_id, user_id


async def _expire_seed_session(session_factory, conversation_id: uuid.UUID) -> None:
    async with session_factory() as session:
        active = await SessionRepository().get_active(session, conversation_id)
        assert active is not None
        active.started_at = datetime.now(UTC) - timedelta(hours=4)
        active.expires_at = active.started_at + SESSION_DURATION
        await session.commit()
