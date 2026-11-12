"""Message flows: ingress (user), AI replies, operator replies.

Rules implemented here (services, not route handlers):
- P-06 (PROPOSED): user auto-provisioning from channel identity;
- P-04 (PROPOSED): routing to the user's latest ticket;
- D-005: one ticket per conversation, messages never split it;
- D-007/D-008: 3-hour sessions, new session on the next message;
- D-011: operator reply -> PENDING_USER;
- D-010 revised: a resolved ticket is terminal, the user's next message
  starts a new ticket (no reopen);
- D-039 (owner): "Обработка ИИ" — a user message in the AI dialog moves the
  ticket to AI_PROCESSING, the AI answer completes it; in a human dialog
  the message targets OPEN instead;
- G-10: sequence_no allocated atomically in the transaction;
- transactional outbox: the message and its event commit together.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict, TransitionNotAllowed
from app.domain.state_machines import (
    DialogTrigger,
    TicketTrigger,
    next_dialog_mode,
    next_ticket_status,
)
from app.models import (
    AuditActorType,
    Conversation,
    ConversationSession,
    DialogMode,
    Message,
    MessageAuthorType,
    Ticket,
    TicketStatus,
)
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.tickets import TicketRepository
from app.repositories.users import UserRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService
from app.services.outbox import OutboxService
from app.services.sessions import SessionService
from app.services.tickets import RoutingResult, TicketService


@dataclass
class IngestResult:
    message: Message
    conversation: Conversation
    ticket: Ticket
    # Filled for ingress results; replies do not touch sessions.
    session: ConversationSession | None
    conversation_created: bool
    ticket_reopened: bool
    deduplicated: bool = False


class MessageService:
    def __init__(
        self,
        users: UserRepository | None = None,
        ticket_service: TicketService | None = None,
        messages: MessageRepository | None = None,
        conversations: ConversationRepository | None = None,
        sessions: SessionService | None = None,
        outbox: OutboxService | None = None,
        audit: AuditService | None = None,
        ticket_repo: TicketRepository | None = None,
    ) -> None:
        self._users = users or UserRepository()
        self._ticket_service = ticket_service or TicketService()
        self._messages = messages or MessageRepository()
        self._conversations = conversations or ConversationRepository()
        self._sessions = sessions or SessionService()
        self._outbox = outbox or OutboxService()
        self._audit = audit or AuditService()
        self._ticket_repo = ticket_repo or TicketRepository()

    async def handle_incoming_user_message(
        self,
        session: AsyncSession,
        *,
        channel_type: str,
        external_user_id: str,
        text: str,
        external_user_name: str | None = None,
        external_post_id: str | None = None,
        source_created_at: datetime | None = None,
        channel_id: uuid.UUID | None = None,
    ) -> IngestResult:
        """Ingress flow for one user message from Tag (via the bot). Own transaction."""
        async with unit_of_work(session):
            if external_post_id is not None:
                existing = await self._messages.get_by_external_post_id(
                    session, external_post_id
                )
                if existing is not None:
                    return await self._rebuild_result(
                        session, existing, deduplicated=True
                    )

            user = await self._users.get_or_create_with_identity(
                session,
                channel_type=channel_type,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
            )
            routing = await self._ticket_service.route_incoming(
                session, user_id=user.id, channel_id=channel_id
            )
            active_session = await self._sessions.ensure_active(
                session, routing.conversation.id
            )
            sequence = await self._conversations.allocate_sequence(
                session, routing.conversation.id
            )
            message = await self._messages.create(
                session,
                conversation_id=routing.conversation.id,
                sequence_no=sequence,
                author_type=MessageAuthorType.USER,
                author_user_id=user.id,
                text=text,
                external_post_id=external_post_id,
                source_created_at=source_created_at,
            )
            await self._apply_ticket_transition(session, routing)
            await self._outbox.register(
                session,
                event_type="message.user_received",
                aggregate_type="message",
                aggregate_id=message.id,
                idempotency_key=f"message:{message.id}",
                payload={
                    "message_id": str(message.id),
                    "conversation_id": str(routing.conversation.id),
                },
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.USER,
                action="message.created",
                entity_type="message",
                entity_id=message.id,
                actor_id=user.id,
                details={
                    "conversation_id": str(routing.conversation.id),
                    "sequence_no": sequence,
                },
            )
            return IngestResult(
                message=message,
                conversation=routing.conversation,
                ticket=routing.ticket,
                session=active_session,
                conversation_created=routing.conversation_created,
                ticket_reopened=routing.ticket_reopened,
            )

    async def add_ai_reply(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        text: str,
    ) -> IngestResult:
        """AI Orchestrator result publication. Own transaction."""
        async with unit_of_work(session):
            return await self.publish_ai_answer(
                session, conversation_id=conversation_id, text=text
            )

    async def publish_ai_answer(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        text: str,
    ) -> IngestResult:
        """Same as add_ai_reply, but INSIDE the caller's transaction (used by
        the AI run service so the run outcome and the published message commit
        atomically). Raises TransitionNotAllowed if the dialog left AI mode."""
        conversation = await self._require_conversation(session, conversation_id)
        if conversation.mode != DialogMode.AI_ACTIVE:
            # AI results are never published after Handoff (D-014).
            raise TransitionNotAllowed(
                "conversation", str(conversation.mode), "AI_REPLY"
            )
        ticket = await self._require_ticket_by_conversation(session, conversation_id)
        sequence = await self._conversations.allocate_sequence(
            session, conversation_id
        )
        message = await self._messages.create(
            session,
            conversation_id=conversation_id,
            sequence_no=sequence,
            author_type=MessageAuthorType.AI,
            text=text,
        )
        # FSM: AI_REPLY completes a processing ticket (D-039).
        await self._transition_ticket(
            session, ticket, TicketTrigger.AI_REPLY
        )
        await self._register_outbound(session, message, conversation_id)
        await self._audit.log(
            session,
            actor_type=AuditActorType.AI,
            action="message.created",
            entity_type="message",
            entity_id=message.id,
            details={"conversation_id": str(conversation_id)},
        )
        return self._result(message, conversation, ticket)

    async def add_operator_reply(
        self,
        session: AsyncSession,
        *,
        ticket_id: uuid.UUID,
        text: str,
        operator_id: uuid.UUID | None = None,
        reply_to_message_id: uuid.UUID | None = None,
    ) -> IngestResult:
        """Public operator reply (stage 7 adds the API and permissions).

        D-011: the ticket goes to PENDING_USER (the operator may preempt the
        AI while it is processing); an AI_ACTIVE dialog becomes HUMAN_ACTIVE.
        Own transaction.
        """
        async with unit_of_work(session):
            ticket = await self._require_ticket(session, ticket_id)
            conversation = await self._require_conversation(
                session, ticket.conversation_id
            )
            # Dialog mode: operator engagement takes over from AI (no way back).
            if conversation.mode == DialogMode.AI_ACTIVE:
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
                await session.refresh(conversation)

            sequence = await self._conversations.allocate_sequence(
                session, ticket.conversation_id
            )
            message = await self._messages.create(
                session,
                conversation_id=ticket.conversation_id,
                sequence_no=sequence,
                author_type=MessageAuthorType.OPERATOR,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
            # D-011: operator reply -> PENDING_USER (FSM: from any non-CLOSED).
            await self._transition_ticket(
                session, ticket, TicketTrigger.OPERATOR_REPLY
            )
            await self._register_outbound(session, message, ticket.conversation_id)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="message.created",
                entity_type="message",
                entity_id=message.id,
                actor_id=operator_id,
                details={"conversation_id": str(ticket.conversation_id)},
            )
            return self._result(message, conversation, ticket)

    async def apply_ticket_trigger(
        self,
        session: AsyncSession,
        ticket: Ticket,
        trigger: TicketTrigger,
    ) -> None:
        """Public FSM helper (with the bounded conflict retry) for other
        services that move a ticket inside their own transaction."""
        return await self._transition_ticket(session, ticket, trigger)

    async def _apply_ticket_transition(
        self, session: AsyncSession, routing: RoutingResult
    ) -> None:
        """Ticket status after a user message (D-039: AI_PROCESSING only in
        the AI dialog; in a human dialog the message targets OPEN)."""
        ticket = routing.ticket
        await self._transition_ticket(
            session,
            ticket,
            TicketTrigger.USER_MESSAGE,
            dialog_mode=str(routing.conversation.mode),
        )

    async def _transition_ticket(
        self,
        session: AsyncSession,
        ticket: Ticket,
        trigger: TicketTrigger,
        *,
        dialog_mode: str | None = None,
    ) -> None:
        """Apply the FSM transition with a bounded retry on version conflict.

        Two concurrent writers (e.g. two user messages in one dialog) may both
        observe state_version N: the loser gets StateConflict from the
        optimistic UPDATE, re-reads the fresh status and replays the FSM —
        its own target usually becomes a no-op that way.
        """
        retries = 3
        for attempt in range(retries):
            target = TicketStatus(
                next_ticket_status(str(ticket.status), trigger, dialog_mode)
            )
            if target == ticket.status:
                return  # nothing to write (e.g. already AI_PROCESSING)
            try:
                await self._ticket_repo.change_status(
                    session,
                    ticket.id,
                    to_status=target,
                    expected_state_version=ticket.state_version,
                )
                await session.refresh(ticket)
                return
            except StateConflict:
                if attempt == retries - 1:
                    raise
                # Another writer moved the ticket first: re-read and replay.
                await session.refresh(ticket)

    async def _register_outbound(
        self, session: AsyncSession, message: Message, conversation_id: uuid.UUID
    ) -> None:
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

    async def _require_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._conversations.get(session, conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        return conversation

    async def _require_ticket(self, session: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
        ticket = await self._ticket_repo.get(session, ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found")
        return ticket

    async def _require_ticket_by_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Ticket:
        ticket = await self._ticket_repo.get_by_conversation(session, conversation_id)
        if ticket is None:
            raise ValueError(f"No ticket for conversation {conversation_id}")
        return ticket

    async def _rebuild_result(
        self, session: AsyncSession, message: Message, *, deduplicated: bool
    ) -> IngestResult:
        """Dedup fast path: the message already exists, nothing changes."""
        conversation = await self._require_conversation(session, message.conversation_id)
        ticket = await self._require_ticket_by_conversation(
            session, message.conversation_id
        )
        active = await self._sessions.ensure_active(session, conversation.id)
        return IngestResult(
            message=message,
            conversation=conversation,
            ticket=ticket,
            session=active,
            conversation_created=False,
            ticket_reopened=False,
            deduplicated=deduplicated,
        )

    def _result(
        self, message: Message, conversation: Conversation, ticket: Ticket
    ) -> IngestResult:
        return IngestResult(
            message=message,
            conversation=conversation,
            ticket=ticket,
            session=None,
            conversation_created=False,
            ticket_reopened=False,
        )
