"""Ticket persistence, including P-04 routing queries and optimistic status changes."""

import uuid
from datetime import datetime

from sqlalchemy import String, case, desc, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict
from app.models import (
    Conversation,
    ConversationSession,
    Message,
    SessionStatus,
    Tag,
    Ticket,
    TicketStatus,
    TicketTag,
    User,
    UserIdentity,
)


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

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, *, limit: int = 20
    ) -> list[Ticket]:
        """Recent ticket history for the operator customer card (docs/06 §5)."""
        stmt = (
            select(Ticket)
            .where(Ticket.user_id == user_id)
            .order_by(desc(Ticket.updated_at), desc(Ticket.created_at))
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

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
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        user_query: str | None = None,
        ticket_query: str | None = None,
        text_query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        """Operator queue: newest activity first (stage 7, docs/06 §2).

        History-page filters (stage 9 round 5): created_from/created_to,
        user_query (user UUID, login fragment or display-name fragment),
        ticket_query (full UUID or short-id prefix of the ticket) and
        text_query (substring of any message in the conversation)."""
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
        if created_from is not None:
            stmt = stmt.where(Ticket.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(Ticket.created_at < created_to)
        if user_query:
            cleaned = user_query.strip()
            try:
                found_user_id = uuid.UUID(cleaned)
            except ValueError:
                found_user_id = None
            stmt = stmt.join(User, User.id == Ticket.user_id)
            if found_user_id is not None:
                stmt = stmt.where(Ticket.user_id == found_user_id)
            else:
                # Login fragment (Tag identity user_name) or display name.
                pattern = f"%{cleaned.lower()}%"
                identity_ids = select(UserIdentity.user_id).where(
                    func.lower(UserIdentity.external_user_name).like(pattern)
                )
                stmt = stmt.where(
                    or_(
                        Ticket.user_id.in_(identity_ids),
                        func.lower(User.display_name).like(pattern),
                    )
                )
        if ticket_query:
            cleaned = ticket_query.strip().lower()
            try:
                as_uuid = uuid.UUID(cleaned)
            except ValueError:
                as_uuid = None
            if as_uuid is not None:
                stmt = stmt.where(Ticket.id == as_uuid)
            else:
                prefix = cleaned.replace("-", "")[:8]
                stmt = stmt.where(
                    func.replace(func.cast(Ticket.id, String), "-", "").like(
                        f"{prefix}%"
                    )
                )
        if text_query:
            pattern = f"%{text_query.strip().lower()}%"
            stmt = stmt.where(
                Ticket.conversation_id.in_(
                    select(Message.conversation_id).where(
                        func.lower(Message.text).like(pattern)
                    )
                )
            )
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

    async def set_pending_assignee(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        pending_assignee_id: uuid.UUID | None,
    ) -> None:
        """Queue the ticket for the operator until a slot frees up."""
        result = await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(pending_assignee_id=pending_assignee_id)
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise StateConflict(f"Ticket {ticket_id} disappeared")

    async def count_active_for(
        self, session: AsyncSession, operator_id: uuid.UUID
    ) -> int:
        """Non-closed tickets currently assigned to the operator (capacity)."""
        stmt = (
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.assignee_id == operator_id,
                Ticket.status.not_in((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
            )
        )
        return int((await session.scalar(stmt)) or 0)

    async def list_active_for_operator(
        self, session: AsyncSession, operator_id: uuid.UUID
    ) -> list[Ticket]:
        """Active tickets currently assigned to the operator."""
        stmt = (
            select(Ticket)
            .where(
                Ticket.assignee_id == operator_id,
                Ticket.status.not_in((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
            )
            .order_by(Ticket.created_at, Ticket.id)
        )
        return list((await session.scalars(stmt)).all())

    async def list_timed_out(
        self, session: AsyncSession, *, now: datetime
    ) -> list[uuid.UUID]:
        """Owner rule (2026-11-17): tickets whose dialog has no unexpired
        ACTIVE session and that are still non-terminal must be closed by the
        session timeout. Called right after the session expiry sweep."""
        stmt = (
            select(Ticket.id)
            .where(
                Ticket.status.in_(
                    [
                        TicketStatus.NEW,
                        TicketStatus.AI_PROCESSING,
                        TicketStatus.OPEN,
                        TicketStatus.PENDING_USER,
                    ]
                ),
                ~exists(
                    select(ConversationSession.id).where(
                        ConversationSession.conversation_id
                        == Ticket.conversation_id,
                        ConversationSession.status == SessionStatus.ACTIVE,
                        ConversationSession.expires_at > now,
                    )
                ),
            )
            .limit(100)
        )
        return list((await session.scalars(stmt)).all())

    async def list_unassigned_active(self, session: AsyncSession) -> list[Ticket]:
        """Unassigned active tickets, highest priority first (owner rule:
        high-priority chats are handed out before lower ones).

        Owner rule 2026-11-13: AI-owned dialogs (AI_PROCESSING) are NOT in
        the routing queue — nobody gave them to an operator, so auto-routing
        must never pull them out of the AI."""
        rank = case(
            (Ticket.priority == "URGENT", 3),
            (Ticket.priority == "HIGH", 2),
            (Ticket.priority == "NORMAL", 1),
            else_=0,
        )
        stmt = (
            select(Ticket)
            .where(
                Ticket.assignee_id.is_(None),
                Ticket.status.not_in(
                    (TicketStatus.RESOLVED, TicketStatus.CLOSED, TicketStatus.AI_PROCESSING)
                ),
            )
            .order_by(desc(rank), Ticket.created_at, Ticket.id)
        )
        return list((await session.scalars(stmt)).all())

    async def oldest_pending_for(
        self, session: AsyncSession, operator_id: uuid.UUID
    ) -> Ticket | None:
        """Oldest ticket queued for this operator (FIFO deferred assignment)."""
        stmt = (
            select(Ticket)
            .where(
                Ticket.pending_assignee_id == operator_id,
                Ticket.status.not_in((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
            )
            .order_by(Ticket.created_at, Ticket.id)
            .limit(1)
        )
        return (await session.scalars(stmt)).first()

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

    async def set_priority(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        priority: str,
    ) -> None:
        """Set the priority (docs/03 #16); plain write, no version bump."""
        result = await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(priority=priority)
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise StateConflict(f"Ticket {ticket_id} disappeared")
