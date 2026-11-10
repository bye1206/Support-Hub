"""Ticket persistence, including P-04 routing queries and optimistic status changes."""

import uuid

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict
from app.models import Conversation, Tag, Ticket, TicketStatus, TicketTag


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

    async def list_filtered(
        self,
        session: AsyncSession,
        *,
        status: TicketStatus | None = None,
        assignee_id: uuid.UUID | None = None,
        unassigned_only: bool = False,
        category_id: uuid.UUID | None = None,
        tag_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        """Operator queue: newest activity first (stage 7, docs/06 §2)."""
        stmt = (
            select(Ticket)
            .join(Conversation, Conversation.id == Ticket.conversation_id)
            .order_by(desc(Conversation.updated_at), desc(Ticket.created_at))
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(Ticket.status == status)
        if assignee_id is not None:
            stmt = stmt.where(Ticket.assignee_id == assignee_id)
        if unassigned_only:
            stmt = stmt.where(Ticket.assignee_id.is_(None))
        if category_id is not None:
            stmt = stmt.where(Ticket.category_id == category_id)
        if tag_name is not None:
            # PK (ticket_id, tag_id) prevents duplicate rows: no DISTINCT.
            stmt = (
                stmt.join(TicketTag, TicketTag.ticket_id == Ticket.id)
                .join(Tag, Tag.id == TicketTag.tag_id)
                .where(func.lower(Tag.name) == tag_name.lower())
            )
        return list((await session.scalars(stmt)).all())

    async def set_assignee(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        assignee_id: uuid.UUID | None,
    ) -> None:
        """Manual assignment (docs/06 §6); rowcount check catches a deleted
        ticket - assignment itself is a plain write, no version bump."""
        result = await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(assignee_id=assignee_id)
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise StateConflict(f"Ticket {ticket_id} disappeared")

    async def set_category(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        category_id: uuid.UUID | None,
    ) -> None:
        """Set the main category (D-026); plain write, no version bump."""
        result = await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(category_id=category_id)
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise StateConflict(f"Ticket {ticket_id} disappeared")
