"""Ticket lifecycle: P-04 routing, reopen (D-010), resolve/close, dialog mode."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict
from app.domain.state_machines import (
    DialogTrigger,
    TicketTrigger,
    next_dialog_mode,
    next_ticket_status,
)
from app.models import (
    AuditActorType,
    Conversation,
    DialogMode,
    Ticket,
    TicketStatus,
)
from app.repositories.conversations import ConversationRepository
from app.repositories.tickets import TicketRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService
from app.services.sessions import SessionService


@dataclass
class RoutingResult:
    conversation: Conversation
    ticket: Ticket
    conversation_created: bool
    ticket_reopened: bool


class TicketService:
    def __init__(
        self,
        tickets: TicketRepository | None = None,
        conversations: ConversationRepository | None = None,
        sessions: SessionService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._tickets = tickets or TicketRepository()
        self._conversations = conversations or ConversationRepository()
        self._sessions = sessions or SessionService()
        self._audit = audit or AuditService()

    async def route_incoming(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        channel_id: uuid.UUID | None = None,
    ) -> RoutingResult:
        """P-04 (PROPOSED): attach the incoming message to the user's latest
        ticket; RESOLVED reopens it (D-010); CLOSED or none -> new ticket in a
        new dialog (D-005). Caller's transaction."""
        last = await self._tickets.get_last_for_user(session, user_id)

        if last is None or last.status == TicketStatus.CLOSED:
            conversation = await self._conversations.create(
                session, user_id=user_id, channel_id=channel_id
            )
            ticket = await self._tickets.create(
                session, conversation_id=conversation.id, user_id=user_id
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.SYSTEM,
                action="ticket.created",
                entity_type="ticket",
                entity_id=ticket.id,
                details={"conversation_id": str(conversation.id)},
            )
            return RoutingResult(
                conversation=conversation,
                ticket=ticket,
                conversation_created=True,
                ticket_reopened=False,
            )

        existing_conversation = await self._conversations.get(
            session, last.conversation_id
        )
        if existing_conversation is None:  # pragma: no cover - FK guarantees existence
            raise StateConflict(f"Conversation {last.conversation_id} missing")

        if last.status == TicketStatus.RESOLVED:
            # D-010: continuation of the same problem reopens the ticket.
            await self._tickets.change_status(
                session,
                last.id,
                to_status=TicketStatus.OPEN,
                expected_state_version=last.state_version,
            )
            await session.refresh(last)
            await self._audit.log(
                session,
                actor_type=AuditActorType.SYSTEM,
                action="ticket.reopened",
                entity_type="ticket",
                entity_id=last.id,
                details={"conversation_id": str(existing_conversation.id)},
            )
            return RoutingResult(
                conversation=existing_conversation,
                ticket=last,
                conversation_created=False,
                ticket_reopened=True,
            )

        return RoutingResult(
            conversation=existing_conversation,
            ticket=last,
            conversation_created=False,
            ticket_reopened=False,
        )

    async def resolve(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Ticket:
        """Operator action: resolve (docs/01 §3). Own transaction."""
        async with unit_of_work(session):
            ticket = await self._apply_status(
                session, ticket_id, TicketTrigger.OPERATOR_RESOLVED
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.resolved",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
            )
            return ticket

    async def close(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Ticket:
        """Operator action: final close; the dialog closes with the ticket."""
        async with unit_of_work(session):
            ticket = await self._apply_status(
                session, ticket_id, TicketTrigger.OPERATOR_CLOSED
            )
            conversation = await self._conversations.get(
                session, ticket.conversation_id
            )
            if conversation is None:  # pragma: no cover - FK guarantees existence
                raise StateConflict("Conversation missing")
            new_mode = next_dialog_mode(
                str(conversation.mode), DialogTrigger.CONVERSATION_CLOSED
            )
            await self._conversations.change_mode(
                session,
                conversation.id,
                from_mode=conversation.mode,
                to_mode=DialogMode(new_mode),
                expected_state_version=conversation.state_version,
            )
            await session.refresh(conversation)
            await self._sessions.end_active(session, conversation.id)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.closed",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"conversation_id": str(conversation.id)},
            )
            return ticket

    async def _apply_status(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        trigger: TicketTrigger,
    ) -> Ticket:
        ticket = await self._tickets.get(session, ticket_id)
        if ticket is None:
            raise StateConflict(f"Ticket {ticket_id} not found")
        target = TicketStatus(next_ticket_status(str(ticket.status), trigger))
        if target != ticket.status:
            await self._tickets.change_status(
                session,
                ticket_id,
                to_status=target,
                expected_state_version=ticket.state_version,
            )
            await session.refresh(ticket)
        return ticket
