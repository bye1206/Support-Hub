"""Owner rule (2026-11-17): the 3-hour session timeout closes the ticket.

Two paths:
- worker sweep (`expire_sessions`): tickets whose dialog has no live session
  are closed with a farewell note to the user and an operator-facing note;
- lazy path: a user message arriving on a timed-out dialog closes the old
  ticket and starts a fresh dialog (new ticket + greeting).
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    Conversation,
    ConversationSession,
    Message,
    MessageAuthorType,
    OutboxEvent,
    Ticket,
    TicketStatus,
)
from app.services.messages import MessageService
from app.services.tickets import TicketService
from app.worker.tasks import expire_sessions
from tests.test_ai_runs import _seed_user_message


async def _expire_dialog_session(session_factory, conversation_id: uuid.UUID) -> None:
    """Push the dialog's ACTIVE session into the past (3 hours are over)."""
    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(ConversationSession).where(
                        ConversationSession.conversation_id == conversation_id
                    )
                )
            ).all()
        )
        # The DB CHECK pins expires_at = started_at + 3h: shift both into the
        # past instead of only moving expires_at.
        for row in rows:
            row.started_at = row.started_at - timedelta(hours=4)
            row.expires_at = row.started_at + timedelta(hours=3)
        await session.commit()


async def _system_texts(session_factory, conversation_id: uuid.UUID) -> list[str]:
    async with session_factory() as check:
        rows = (
            await check.scalars(
                select(Message.text).where(
                    Message.conversation_id == conversation_id,
                    Message.author_type == MessageAuthorType.SYSTEM,
                )
            )
        ).all()
        return list(rows)


@pytest.mark.anyio
async def test_worker_sweep_closes_timed_out_ticket(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)

    await _expire_dialog_session(session_factory, conversation_id)
    await expire_sessions({"session_factory": session_factory})

    async with session_factory() as check:
        ticket = (
            await check.scalars(
                select(Ticket).where(Ticket.conversation_id == conversation_id)
            )
        ).one()
        assert ticket.status == TicketStatus.CLOSED
        conversation = await check.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.mode.value == "CLOSED"

    texts = await _system_texts(session_factory, conversation_id)
    assert any("время сессии ограничено" in t for t in texts)
    assert any("таймаут" in t for t in texts)

    async with session_factory() as check:
        outbound = (
            await check.scalars(
                select(OutboxEvent.event_type).where(
                    OutboxEvent.event_type == "message.outbound"
                )
            )
        ).all()
    # The greeting note + the timeout farewell both went out to Tag.
    assert len(outbound) >= 2


@pytest.mark.anyio
async def test_message_after_timeout_starts_new_ticket(session_factory) -> None:
    service = MessageService()
    _, old_conversation_id = await _seed_user_message(
        session_factory, external_user_id="timeout-user"
    )
    await _expire_dialog_session(session_factory, old_conversation_id)

    async with session_factory() as session:
        result = await service.handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id="timeout-user",
            text="проблема не решена",
        )

    # The timed-out dialog was closed; the message lives in a new one.
    assert result.conversation.id != old_conversation_id
    assert result.conversation_created is True
    assert result.ticket.status == TicketStatus.NEW

    async with session_factory() as check:
        old_ticket = (
            await check.scalars(
                select(Ticket).where(Ticket.conversation_id == old_conversation_id)
            )
        ).one()
        assert old_ticket.status == TicketStatus.CLOSED
        old_conversation = await check.get(Conversation, old_conversation_id)
        assert old_conversation is not None
        assert old_conversation.mode.value == "CLOSED"


@pytest.mark.anyio
async def test_resolved_ticket_is_not_double_closed(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)
    async with session_factory() as session:
        ticket_id = (
            await session.scalars(
                select(Ticket.id).where(Ticket.conversation_id == conversation_id)
            )
        ).one()
        await TicketService().resolve(session, ticket_id)

    await _expire_dialog_session(session_factory, conversation_id)
    await expire_sessions({"session_factory": session_factory})

    async with session_factory() as check:
        ticket = await check.get(Ticket, ticket_id)
        assert ticket is not None
        assert ticket.status == TicketStatus.RESOLVED  # not downgraded to CLOSED
