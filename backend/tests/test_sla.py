"""Operator reply SLA (owner request, 2026-11-19).

Covered: a user message in a human dialog arms the 15-minute clock; the
AI stage keeps it unarmed; an operator reply records "met"; the breach
sweep flags overdue OPEN tickets and writes history; transitions land in
the status history.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Ticket, TicketStatus
from app.services.messages import MessageService
from app.services.tickets import TicketService
from tests.test_ai_runs import USER_ID, _seed_user_message

SLA_MINUTES = 15


async def _get_ticket(session_factory, conversation_id: uuid.UUID) -> Ticket:
    async with session_factory() as session:
        return (
            await session.scalars(
                select(Ticket).where(Ticket.conversation_id == conversation_id)
            )
        ).one()


@pytest.mark.anyio
async def test_ai_stage_has_no_sla_and_history_is_written(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.AI_PROCESSING
    # The AI stage carries no operator SLA.
    assert ticket.sla_deadline is None
    # The greeting + question transitions are in the history.
    async with session_factory() as session:
        from app.models import TicketStatusHistory

        rows = (
            (
                await session.scalars(
                    select(TicketStatusHistory).where(
                        TicketStatusHistory.ticket_id == ticket.id
                    )
                )
            )
            .all()
        )
    assert [(row.kind, row.to_status) for row in rows] == [
        ("status", "AI_PROCESSING")
    ]


@pytest.mark.anyio
async def test_claim_arms_sla_and_user_message_rearms(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)
    service = TicketService()
    async with session_factory() as session:
        ticket = await _get_ticket(session_factory, conversation_id)
        await service.assign(
            session, ticket.id, assignee_id=None, actor_id=None  # type: ignore[arg-type]
        )
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.OPEN
    # Manual assignment arms the reply clock.
    assert ticket.sla_deadline is not None
    deadline = ticket.sla_deadline
    assert deadline - datetime.now(UTC) < timedelta(minutes=SLA_MINUTES)

    # The user answers in the human dialog: the clock restarts.
    async with session_factory() as session:
        await MessageService().handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=USER_ID,
            text="Всё ещё не работает",
        )
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.sla_deadline is not None
    assert ticket.sla_deadline != deadline


@pytest.mark.anyio
async def test_operator_reply_records_sla_met(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)
    ticket = await _get_ticket(session_factory, conversation_id)
    async with session_factory() as session:
        await TicketService().assign(
            session, ticket.id, assignee_id=None, actor_id=None  # type: ignore[arg-type]
        )
    async with session_factory() as session:
        await MessageService().handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=USER_ID,
            text="Всё ещё не работает",
        )
    ticket = await _get_ticket(session_factory, conversation_id)
    async with session_factory() as session:
        await MessageService().add_operator_reply(
            session, ticket_id=ticket.id, text="Проверяем"
        )
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.PENDING_USER
    assert ticket.sla_deadline is None
    async with session_factory() as session:
        from app.models import TicketStatusHistory

        kinds = (
            await session.scalars(
                select(TicketStatusHistory.kind).where(
                    TicketStatusHistory.ticket_id == ticket.id
                )
            )
        ).all()
    assert "sla_met" in [str(k) for k in kinds]


@pytest.mark.anyio
async def test_breach_sweep_flags_overdue_open(session_factory) -> None:
    _, conversation_id = await _seed_user_message(session_factory)
    ticket = await _get_ticket(session_factory, conversation_id)
    async with session_factory() as session:
        await TicketService().assign(
            session, ticket.id, assignee_id=None, actor_id=None  # type: ignore[arg-type]
        )
    ticket = await _get_ticket(session_factory, conversation_id)
    # Pretend the deadline passed long ago.
    async with session_factory() as session:
        fresh = await session.get(Ticket, ticket.id)
        assert fresh is not None
        fresh.sla_deadline = datetime.now(UTC) - timedelta(minutes=30)
        await session.commit()
    breached = await TicketService().breach_overdue_slas(session_factory)
    assert breached == 1
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.sla_breached_at is not None
    # Idempotent: the second sweep does nothing.
    assert await TicketService().breach_overdue_slas(session_factory) == 0
