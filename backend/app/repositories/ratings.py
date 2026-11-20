"""TicketRatingRepository: one satisfaction rating per closed ticket.

Owner request (2026-11-19): the user rates 1-5 via buttons (or a digit
reply); scores 1-3 collect a free-text review in the next message.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket, TicketRating, TicketStatus


class TicketRatingRepository:
    async def for_ticket(
        self, session: AsyncSession, ticket_id: uuid.UUID
    ) -> TicketRating | None:
        return (
            await session.scalars(
                select(TicketRating).where(TicketRating.ticket_id == ticket_id)
            )
        ).first()

    async def create(
        self,
        session: AsyncSession,
        *,
        ticket_id: uuid.UUID,
        score: int,
        target: str | None,
        operator_id: uuid.UUID | None,
    ) -> TicketRating:
        rating = TicketRating(
            ticket_id=ticket_id,
            score=score,
            target=target,
            operator_id=operator_id,
        )
        session.add(rating)
        await session.flush()
        return rating

    async def save_review(
        self, session: AsyncSession, rating: TicketRating, review_text: str
    ) -> TicketRating:
        rating.review_text = review_text
        rating.reviewed_at = datetime.now(UTC)
        await session.flush()
        return rating

    async def avg_by_operators(
        self, session: AsyncSession, operator_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, float]:
        """Average score per operator (crown in the team/admin panels)."""
        if not operator_ids:
            return {}
        from sqlalchemy import func

        rows = await session.execute(
            select(
                TicketRating.operator_id, func.avg(TicketRating.score)
            )
            .where(TicketRating.operator_id.in_(operator_ids))
            .group_by(TicketRating.operator_id)
        )
        return {row[0]: float(row[1]) for row in rows}

    async def latest_awaiting_review_for_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> TicketRating | None:
        """The newest low-score rating without a review on the user's last
        terminal dialog — the review text arrives as their next message."""
        return (
            await session.scalars(
                select(TicketRating)
                .join(Ticket, Ticket.id == TicketRating.ticket_id)
                .where(
                    Ticket.user_id == user_id,
                    Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
                    TicketRating.score <= 3,
                    TicketRating.review_text.is_(None),
                )
                .order_by(TicketRating.created_at.desc())
                .limit(1)
            )
        ).first()
