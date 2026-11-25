"""Satisfaction ratings service (owner request, 2026-11-19).

After the farewell note the user rates 1-5 — either with the Mattermost
buttons (direct mode) or by typing a digit. Scores 1-3 ask for a free
text review that arrives as the user's next message. The rating is
attributed to the AI ("помогло" closure) or to the operator who resolved
the dialog; the target is stamped on the ticket at closure time.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditActorType, Message, Ticket, TicketStatus
from app.repositories.ratings import TicketRatingRepository
from app.services.audit import AuditService
from app.services.outbox import OutboxService
from app.services.tickets import TicketService

logger = logging.getLogger(__name__)

ASK_REVIEW_TEXT = (
    "Спасибо за оценку!\n"
    "Напишите, пожалуйста, отзыв — почему поставили такую оценку? "
    "Отзывы помогают улучшить наш сервис."
)
REVIEW_THANKS_TEXT = "Спасибо за ваш отзыв! Он поможет нам стать лучше."
SCORE_THANKS_TEXT = "Спасибо за вашу оценку!"


class RatingService:
    def __init__(
        self,
        tickets: TicketService | None = None,
        ratings: TicketRatingRepository | None = None,
        outbox: OutboxService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._tickets = tickets or TicketService()
        self._ratings = ratings or TicketRatingRepository()
        self._outbox = outbox or OutboxService()
        self._audit = audit or AuditService()

    async def _send_bot_note(
        self, session: AsyncSession, conversation_id: uuid.UUID, text: str
    ) -> Message:
        message = await self._tickets.create_bot_note(session, conversation_id, text)
        await self._outbox.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=message.id,
            idempotency_key=f"message:{message.id}",
            payload={
                "message_id": str(message.id),
                "conversation_id": str(conversation_id),
            },
        )
        return message

    async def capture_score(
        self,
        session: AsyncSession,
        ticket: Ticket,
        score: int,
        *,
        send_note: bool = True,
    ) -> Message | None:
        """Store the score (idempotent: the first one wins) and answer the
        user; low scores ask for a review. Returns the reply message
        (None when the caller opted out of the note). Caller's transaction.

        Owner (2026-11-25): the button path edits the card itself to
        'Спасибо за оценку N/5' — the extra bot note duplicated it, so the
        button click passes send_note=False. The digit fallback keeps the
        note (there is no card to edit)."""
        if score < 1 or score > 5:
            raise ValueError(f"Score {score} out of range")
        rating = await self._ratings.for_ticket(session, ticket.id)
        if rating is None:
            rating = await self._ratings.create(
                session,
                ticket_id=ticket.id,
                score=score,
                target=ticket.rating_target,
                operator_id=ticket.rating_operator_id,
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.USER,
                action="rating.created",
                entity_type="ticket",
                entity_id=ticket.id,
                details={"score": score, "target": ticket.rating_target},
            )
        if rating.score <= 3:
            return await self._send_bot_note(
                session, ticket.conversation_id, ASK_REVIEW_TEXT
            )
        if not send_note:
            return None
        return await self._send_bot_note(
            session, ticket.conversation_id, SCORE_THANKS_TEXT
        )

    async def capture_review_text(
        self, session: AsyncSession, user_id: uuid.UUID, text: str
    ) -> Message | None:
        """If the user's latest low-score rating awaits a review, save the
        text and thank them. Returns the reply message, or None when the
        text was NOT consumed (the caller then routes the message
        normally)."""
        rating = await self._ratings.latest_awaiting_review_for_user(
            session, user_id
        )
        if rating is None:
            return None
        await self._ratings.save_review(session, rating, text)
        ticket = await session.get(Ticket, rating.ticket_id)
        conversation_id = (
            ticket.conversation_id if ticket is not None else None
        )
        reply = None
        if conversation_id is not None:
            reply = await self._send_bot_note(
                session, conversation_id, REVIEW_THANKS_TEXT
            )
        await self._audit.log(
            session,
            actor_type=AuditActorType.USER,
            action="rating.review",
            entity_type="ticket",
            entity_id=rating.ticket_id,
            details={"review_length": len(text)},
        )
        return reply

    async def ticket_needs_score(
        self, session: AsyncSession, ticket: Ticket, text: str
    ) -> bool:
        """True when the text is a bare digit and the terminal ticket still
        awaits its rating (plain-text fallback when buttons are not used)."""
        if ticket.rating_target is None:
            return False
        if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            return False
        if await self._ratings.for_ticket(session, ticket.id) is not None:
            return False
        return text.strip() in {"1", "2", "3", "4", "5"}
