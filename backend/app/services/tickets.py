"""Ticket lifecycle: P-04 routing, resolve/close (D-010 revised: terminal), dialog mode."""

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
    Tag,
    Ticket,
    TicketStatus,
)
from app.repositories.ai_runs import AiHandoffRepository
from app.repositories.categories import TicketCategoryRepository
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.operators import OperatorRepository
from app.repositories.tags import TagRepository
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
        operators: OperatorRepository | None = None,
        handoffs: AiHandoffRepository | None = None,
        categories: TicketCategoryRepository | None = None,
        tags: TagRepository | None = None,
        channels: ChannelRepository | None = None,
    ) -> None:
        self._tickets = tickets or TicketRepository()
        self._conversations = conversations or ConversationRepository()
        self._sessions = sessions or SessionService()
        self._audit = audit or AuditService()
        self._operators = operators or OperatorRepository()
        self._handoffs = handoffs or AiHandoffRepository()
        self._categories = categories or TicketCategoryRepository()
        self._tags = tags or TagRepository()
        self._channels = channels or ChannelRepository()

    async def route_incoming(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        channel_id: uuid.UUID | None = None,
    ) -> RoutingResult:
        """P-04: attach the incoming message to the user's latest OPEN ticket;
        RESOLVED or CLOSED (D-010 revised, owner: no reopen) or none -> a new
        ticket in a new dialog (D-005). Caller's transaction."""
        last = await self._tickets.get_last_for_user(session, user_id)

        if (
            last is None
            or last.status in (TicketStatus.CLOSED, TicketStatus.RESOLVED)
        ):
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
            await self._auto_assign(session, ticket)
            await self._auto_tag_from_channel(session, ticket, channel_id)
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

        return RoutingResult(
            conversation=existing_conversation,
            ticket=last,
            conversation_created=False,
            ticket_reopened=False,
        )

    async def _auto_assign(self, session: AsyncSession, ticket: Ticket) -> None:
        """D-031 auto-assignment (least-loaded active operator), flag-gated.
        Caller's transaction; no candidates -> the ticket stays unassigned."""
        from app.config import get_settings

        if not get_settings().auto_assign_enabled:
            return
        assignee = await self._operators.least_loaded_active(session)
        if assignee is None:
            return
        await self._tickets.set_assignee(
            session, ticket.id, assignee_id=assignee.id
        )
        await session.refresh(ticket)
        await self._audit.log(
            session,
            actor_type=AuditActorType.SYSTEM,
            action="ticket.assigned",
            entity_type="ticket",
            entity_id=ticket.id,
            details={"assignee_id": str(assignee.id), "auto": True},
        )

    async def _auto_tag_from_channel(
        self, session: AsyncSession, ticket: Ticket, channel_id: uuid.UUID | None
    ) -> None:
        """Tag the new ticket with the source channel/service name (P-28),
        flag-gated. Caller's transaction; idempotent for a new ticket."""
        from app.config import get_settings

        if channel_id is None or not get_settings().auto_tag_from_channel:
            return
        channel = await self._channels.get(session, channel_id)
        if channel is None or not channel.display_name:
            return
        tag = await self._tags.get_or_create_by_name(
            session, name=channel.display_name
        )
        linked = await self._tags.list_for_ticket(session, ticket.id)
        if any(t.id == tag.id for t in linked):
            return
        await self._tags.link(session, ticket_id=ticket.id, tag=tag)
        await self._audit.log(
            session,
            actor_type=AuditActorType.SYSTEM,
            action="ticket.tag_added",
            entity_type="ticket",
            entity_id=ticket.id,
            details={"tag_id": str(tag.id), "tag_name": tag.name, "auto": True},
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

    async def assign(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        assignee_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> Ticket:
        """Manual assignment (docs/06 §6); D-031 auto-assignment stays behind
        a flag (P-07). Own transaction."""
        async with unit_of_work(session):
            ticket = await self._tickets.get(session, ticket_id)
            if ticket is None:
                raise ValueError(f"Ticket {ticket_id} not found")
            if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                # D-010 revised: a completed ticket is terminal — assignment
                # would silently reopen it. The user starts a new ticket.
                raise ValueError(
                    f"Ticket {ticket_id} is {ticket.status.value} and cannot be assigned"
                )
            if assignee_id is not None:
                assignee = await self._operators.get(session, assignee_id)
                if assignee is None:
                    raise ValueError(f"Operator {assignee_id} not found")
                if not assignee.is_active:
                    raise ValueError(f"Operator {assignee_id} is deactivated")
            await self._tickets.set_assignee(
                session, ticket_id, assignee_id=assignee_id
            )
            await session.refresh(ticket)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.assigned",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"assignee_id": str(assignee_id) if assignee_id else None},
            )
            return ticket

    async def set_priority(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        priority: str,
        actor_id: uuid.UUID,
    ) -> Ticket:
        """Set the priority (NORMAL/HIGH/URGENT); operator action. Own tx."""
        async with unit_of_work(session):
            ticket = await self._tickets.get(session, ticket_id)
            if ticket is None:
                raise ValueError(f"Ticket {ticket_id} not found")
            await self._tickets.set_priority(session, ticket_id, priority=priority)
            await session.refresh(ticket)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.priority_changed",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"priority": priority},
            )
            return ticket

    async def set_category(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        category_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> Ticket:
        """Set the main category (D-026); null clears it. Own transaction."""
        async with unit_of_work(session):
            ticket = await self._tickets.get(session, ticket_id)
            if ticket is None:
                raise ValueError(f"Ticket {ticket_id} not found")
            if category_id is not None:
                category = await self._categories.get(session, category_id)
                if category is None:
                    raise ValueError(f"Category {category_id} not found or inactive")
            await self._tickets.set_category(
                session, ticket_id, category_id=category_id
            )
            await session.refresh(ticket)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.category_changed",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"category_id": str(category_id) if category_id else None},
            )
            return ticket

    async def add_tag(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        tag_name: str,
        actor_id: uuid.UUID,
    ) -> Tag:
        """Attach a tag by name (get_or_create, P-23); idempotent.
        Own transaction."""
        async with unit_of_work(session):
            ticket = await self._tickets.get(session, ticket_id)
            if ticket is None:
                raise ValueError(f"Ticket {ticket_id} not found")
            tag = await self._tags.get_or_create_by_name(session, name=tag_name)
            linked = await self._tags.list_for_ticket(session, ticket_id)
            if not any(t.id == tag.id for t in linked):
                await self._tags.link(session, ticket_id=ticket_id, tag=tag)
                await self._audit.log(
                    session,
                    actor_type=AuditActorType.OPERATOR,
                    action="ticket.tag_added",
                    entity_type="ticket",
                    entity_id=ticket_id,
                    actor_id=actor_id,
                    details={"tag_id": str(tag.id), "tag_name": tag.name},
                )
            return tag

    async def remove_tag(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        tag_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Detach a tag; the tag row itself survives (P-23). Own transaction."""
        async with unit_of_work(session):
            ticket = await self._tickets.get(session, ticket_id)
            if ticket is None:
                raise ValueError(f"Ticket {ticket_id} not found")
            removed = await self._tags.unlink(
                session, ticket_id=ticket_id, tag_id=tag_id
            )
            if not removed:
                raise ValueError(f"Tag {tag_id} is not linked to ticket {ticket_id}")
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.tag_removed",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"tag_id": str(tag_id)},
            )

    async def list_tags(
        self, session: AsyncSession, ticket_id: uuid.UUID
    ) -> list[Tag]:
        return await self._tags.list_for_ticket(session, ticket_id)

    async def accept_handoff(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        """The operator claims the dialog offered by AI (D-014 one way):
        HUMAN_PENDING -> HUMAN_ACTIVE, the open handoff becomes accepted.
        Own transaction. Idempotency: accepting twice is an error (410-style
        ValueError; the API maps it to 409)."""
        async with unit_of_work(session):
            handoff = await self._handoffs.get_accepted(session, conversation_id=conversation_id)
            if handoff is not None:
                raise ValueError(f"Handoff of conversation {conversation_id} is already accepted")
            conversation = await self._conversations.get(session, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation {conversation_id} not found")
            if conversation.mode != DialogMode.HUMAN_PENDING:
                raise ValueError(
                    f"Conversation {conversation_id} is not awaiting an operator "
                    f"(mode={conversation.mode})"
                )
            # Claim: HUMAN_PENDING -> HUMAN_ACTIVE (docs/01 §4).
            new_mode = next_dialog_mode(
                str(conversation.mode), DialogTrigger.OPERATOR_TOOK_OVER
            )
            await self._conversations.change_mode(
                session,
                conversation.id,
                from_mode=conversation.mode,
                to_mode=DialogMode(new_mode),
                expected_state_version=conversation.state_version,
            )
            # Mark the newest open handoff accepted (partial unique: one).
            await self._handoffs.accept_latest_open(session, conversation_id=conversation_id)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="handoff.accepted",
                entity_type="conversation",
                entity_id=conversation_id,
                actor_id=actor_id,
            )
