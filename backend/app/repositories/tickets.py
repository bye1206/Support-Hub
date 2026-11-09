"""Ticket persistence, including P-04 routing queries and optimistic status changes."""

import uuid

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict
from app.models import Conversation, Ticket, TicketStatus


class TicketRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        status: TicketStatus = TicketStatus.NEW,
    ) -> Ticket:
        ticket = Ticket(
            conversation_id=conversation_id, user_id=user_id, status=status
        )
        session.add(ticket)
        await session.flush()
        return ticket

    async def get_last_for_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> Ticket | None:
        """The user's most recent ticket (P-04 routes by it)."""
        stmt = (
            select(Ticket)
            .join(Conversation, Conversation.id == Ticket.conversation_id)
            .where(Ticket.user_id == user_id)
            .order_by(desc(Conversation.created_at), desc(Ticket.created_at))
            .limit(1)
        )
        return (await session.scalars(stmt)).first()

    async def get(
        self, session: AsyncSession, ticket_id: uuid.UUID
    ) -> Ticket | None:
        return await session.get(Ticket, ticket_id)

    async def get_by_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Ticket | None:
        """One ticket per conversation (D-005): UNIQUE(conversation_id)."""
        stmt = select(Ticket).where(Ticket.conversation_id == conversation_id).limit(1)
        return (await session.scalars(stmt)).first()

    async def change_status(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        to_status: TicketStatus,
        expected_state_version: int,
    ) -> int:
        """Optimistic status update; returns the new state_version (G-11 base)."""
        result = await session.execute(
            update(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.state_version == expected_state_version,
            )
            .values(
                status=to_status, state_version=Ticket.state_version + 1
            )
            .returning(Ticket.state_version)
        )
        new_version = result.scalar_one_or_none()
        if new_version is None:
            raise StateConflict(f"Ticket {ticket_id} changed concurrently")
        return int(new_version)
