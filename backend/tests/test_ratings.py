"""Rating flow tests (owner request, 2026-11-19).

Closure stamps the attribution target; after the farewell a bare digit
becomes the score, a low score collects a free-text review with the next
message.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    Message,
    MessageAuthorType,
    TicketRating,
    TicketStatus,
)
from app.repositories.ratings import TicketRatingRepository
from app.services.messages import MessageService
from app.services.tickets import TicketService

INGRESS = dict(
    channel_type="tag",
    external_user_id="tag-user-rate",
    external_user_name="Rater",
)


def ingress_kwargs(**overrides: object) -> dict:
    kwargs = dict(INGRESS)
    kwargs.update(overrides)
    return kwargs


async def _resolved_ticket(session, *, operator_id: uuid.UUID | None = None):
    if operator_id is not None:
        from app.models import Operator

        session.add(
            Operator(
                id=operator_id,
                email=f"rate-{uuid.uuid4().hex[:8]}@corp.test",
                display_name="Rate Op",
                is_active=True,
            )
        )
        await session.flush()
    service = TicketService()
    messages = MessageService()
    result = await messages.handle_incoming_user_message(
        session,
        **ingress_kwargs(
            text="здравствуйте",
            external_post_id=f"post-{uuid.uuid4().hex[:8]}",
        ),
    )
    await messages.handle_incoming_user_message(
        session,
        **ingress_kwargs(text="Нужна помощь", external_post_id=None),
    )
    await service.assign(
        session, result.ticket.id, assignee_id=operator_id, actor_id=operator_id
    )
    return await service.resolve(session, result.ticket.id, actor_id=operator_id)


@pytest.mark.anyio
async def test_resolve_stamps_operator_rating_target(session_factory) -> None:
    operator_id = uuid.uuid4()
    async with session_factory() as session:
        ticket = await _resolved_ticket(session, operator_id=operator_id)
        assert ticket.status == TicketStatus.RESOLVED
        assert ticket.rating_target == "OPERATOR"
        assert ticket.rating_operator_id == operator_id
        note = await session.scalar(
            select(Message.text)
            .where(Message.conversation_id == ticket.conversation_id)
            .order_by(Message.sequence_no.desc())
            .limit(1)
        )
        assert note is not None and "оценку от 1 до 5" in note


@pytest.mark.anyio
async def test_digit_reply_becomes_score_for_operator(session_factory) -> None:
    operator_id = uuid.uuid4()
    service = MessageService()
    async with session_factory() as session:
        ticket = await _resolved_ticket(session, operator_id=operator_id)

    async with session_factory() as session:
        result = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="5")
        )
    assert result.message.author_type == MessageAuthorType.SYSTEM
    assert "Спасибо за вашу оценку" in result.message.text

    async with session_factory() as check:
        rating = await TicketRatingRepository().for_ticket(check, ticket.id)
        assert rating is not None
        assert rating.score == 5
        assert rating.target == "OPERATOR"
        assert rating.operator_id == operator_id
        assert rating.review_text is None


@pytest.mark.anyio
async def test_low_score_asks_review_then_saves_text(session_factory) -> None:
    service = MessageService()
    async with session_factory() as session:
        ticket = await _resolved_ticket(session)

    async with session_factory() as session:
        result = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="2")
        )
    assert "Напишите, пожалуйста, отзыв" in result.message.text

    async with session_factory() as session:
        review = await service.handle_incoming_user_message(
            session,
            **ingress_kwargs(text="Долго ждал ответа оператора"),
        )
    assert "Спасибо за ваш отзыв" in review.message.text

    async with session_factory() as check:
        rating = await check.scalar(
            select(TicketRating).where(TicketRating.ticket_id == ticket.id)
        )
        assert rating.score == 2
        assert rating.review_text == "Долго ждал ответа оператора"
        assert rating.reviewed_at is not None
        logged = await check.scalar(
            select(AuditLog).where(AuditLog.action == "rating.review")
        )
        assert logged is not None


@pytest.mark.anyio
async def test_free_text_after_closure_starts_new_ticket(session_factory) -> None:
    """With no pending review a free text is a new dialog, not a score."""
    service = MessageService()
    async with session_factory() as session:
        ticket = await _resolved_ticket(session)

    async with session_factory() as session:
        result = await service.handle_incoming_user_message(
            session, **ingress_kwargs(text="Новая проблема!")
        )
    assert result.conversation.id != ticket.conversation_id
    assert result.conversation_created is True
    # No rating row appeared.
    async with session_factory() as check:
        assert (
            await check.scalar(
                select(TicketRating).where(TicketRating.ticket_id == ticket.id)
            )
            is None
        )
