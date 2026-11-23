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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict, TransitionNotAllowed
from app.domain.state_machines import (
    DialogTrigger,
    TicketTrigger,
    next_dialog_mode,
    next_ticket_status,
)
from app.infra.file_storage import LocalFileStorage
from app.models import (
    AuditActorType,
    Conversation,
    ConversationSession,
    DialogMode,
    Message,
    MessageAuthorType,
    MessageDeliveryState,
    Ticket,
    TicketHistoryKind,
    TicketStatus,
)
from app.repositories.attachments import AttachmentRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.tickets import TicketRepository
from app.repositories.users import UserRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService
from app.services.outbox import OutboxService
from app.services.ratings import RatingService
from app.services.sessions import SessionService
from app.services.tickets import RoutingResult, TicketService


@dataclass
class IncomingFile:
    """One file the user attached (bytes already fetched by the caller)."""

    file_name: str
    mime_type: str
    content: bytes


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
        attachments: AttachmentRepository | None = None,
        storage: LocalFileStorage | None = None,
    ) -> None:
        self._users = users or UserRepository()
        self._ticket_service = ticket_service or TicketService()
        self._messages = messages or MessageRepository()
        self._conversations = conversations or ConversationRepository()
        self._sessions = sessions or SessionService()
        self._outbox = outbox or OutboxService()
        self._audit = audit or AuditService()
        self._ticket_repo = ticket_repo or TicketRepository()
        self._attachments = attachments or AttachmentRepository()
        self._storage = storage or LocalFileStorage()

    async def handle_incoming_user_message(
        self,
        session: AsyncSession,
        *,
        channel_type: str,
        external_user_id: str,
        text: str,
        external_user_name: str | None = None,
        display_name: str | None = None,
        email: str | None = None,
        external_post_id: str | None = None,
        source_created_at: datetime | None = None,
        channel_id: uuid.UUID | None = None,
        files: list[IncomingFile] | None = None,
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
                display_name=display_name,
                email=email,
            )
            # Owner request (2026-11-19): the rating flow — after the
            # farewell a bare digit is the score, a free text on a low
            # score is the review. Both are consumed here instead of
            # starting a new ticket.
            last = await self._ticket_repo.get_last_for_user(session, user.id)
            if (
                last is not None
                and last.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)
                and not files
            ):
                ratings = RatingService()
                reply: Message | None = None
                if await ratings.ticket_needs_score(session, last, text):
                    reply = await ratings.capture_score(
                        session, last, int(text.strip())
                    )
                else:
                    reply = await ratings.capture_review_text(session, user.id, text)
                if reply is not None:
                    return IngestResult(
                        message=reply,
                        conversation=await self._require_conversation(
                            session, last.conversation_id
                        ),
                        ticket=last,
                        session=None,
                        conversation_created=False,
                        ticket_reopened=False,
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
            # Owner request (2026-11-19): files the user attached travel with
            # the message; bytes were downloaded/decoded by the caller.
            if files:
                await self._store_attachments(
                    session,
                    conversation_id=routing.conversation.id,
                    message_id=message.id,
                    files=files,
                )
            if routing.conversation_created:
                # Owner flow (2026-11-13, clarified 2026-11-18): the FIRST
                # message of a dialog gets only the greeting — the question
                # itself is NOT sent to the AI yet, but the ticket already
                # enters "Обработка ИИ" (AI_PROCESSING): the dialog belongs
                # to the AI stage from the very start.
                await self._apply_ticket_transition(session, routing)
                greeting = await self._create_greeting(
                    session, routing.conversation.id, user
                )
                await self._register_outbound(session, greeting, routing.conversation.id)
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
                        "greeting_stage": True,
                    },
                )
                return IngestResult(
                    message=message,
                    conversation=routing.conversation,
                    ticket=routing.ticket,
                    session=active_session,
                    conversation_created=True,
                    ticket_reopened=False,
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
        attachment_ids: list[uuid.UUID] | None = None,
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
                author_operator_id=operator_id,
                reply_to_message_id=reply_to_message_id,
            )
            # Owner request (2026-11-19): files uploaded from the composer
            # beforehand (message_id NULL) are linked to the sent reply.
            if attachment_ids:
                await self._attachments.link_to_message(
                    session,
                    attachment_ids,
                    conversation_id=ticket.conversation_id,
                    message_id=message.id,
                )
            # The operator answered: the reply SLA clock stops; if a deadline
            # was armed, the history gets a "met" row (durations modal).
            deadline_was_armed = ticket.sla_deadline is not None
            await self._ticket_repo.clear_sla(session, ticket.id)
            if deadline_was_armed:
                await self._ticket_repo.add_history(
                    session,
                    ticket_id=ticket.id,
                    kind=TicketHistoryKind.SLA_MET,
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
        # Owner request (2026-11-19): the operator has 15 minutes to reply.
        # A user message in a HUMAN dialog (re)arms the clock; a message in
        # the AI stage stops it (no operator SLA there).
        if ticket.status == TicketStatus.OPEN:
            from datetime import UTC, datetime, timedelta

            await self._ticket_repo.set_sla_deadline(
                session,
                ticket.id,
                deadline=datetime.now(UTC) + timedelta(minutes=15),
            )
        elif ticket.status == TicketStatus.AI_PROCESSING:
            await self._ticket_repo.clear_sla(session, ticket.id)

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
                # Owner request (2026-11-19): every transition lands in the
                # status history (the SLA modal renders durations from it).
                await self._ticket_repo.add_history(
                    session,
                    ticket_id=ticket.id,
                    kind=TicketHistoryKind.STATUS,
                    from_status=str(ticket.status),
                    to_status=str(target),
                )
                await session.refresh(ticket)
                return
            except StateConflict:
                if attempt == retries - 1:
                    raise
                # Another writer moved the ticket first: re-read and replay.
                await session.refresh(ticket)

    async def _create_greeting(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        user: Any,
    ) -> Message:
        """Owner flow step 2 (2026-11-13): greeting on the user's first
        message, addressed by FIRST name only (owner 2026-11-23: no
        patronymic/surname in the salutation)."""
        full_name = (getattr(user, "display_name", None) or "").strip()
        first_name = full_name.split()[0] if full_name.split() else ""
        salutation = f"Добрый день, {first_name}!" if first_name else "Добрый день!"
        sequence = await self._conversations.allocate_sequence(
            session, conversation_id
        )
        return await self._messages.create(
            session,
            conversation_id=conversation_id,
            sequence_no=sequence,
            author_type=MessageAuthorType.SYSTEM,
            delivery_state=MessageDeliveryState.DELIVERED,
            text=(
                f"{salutation} Вы обратились в чат технической поддержки "
                "пользователей офисов. Напишите ваш вопрос."
            ),
        )

    async def _register_outbound(
        self, session: AsyncSession, message: Message, conversation_id: uuid.UUID
    ) -> None:
        # Owner request (2026-11-19): the webhook-mode bot receives the file
        # metadata plus a tokenized download URL; direct mode resolves the
        # files itself and ignores these extra keys.
        attachments = await self._attachments.for_message(session, message.id)
        payload: dict[str, Any] = {
            "message_id": str(message.id),
            "conversation_id": str(conversation_id),
        }
        if attachments:
            from app.config import get_settings

            settings = get_settings()
            base = settings.app_base_url.rstrip("/")
            token = settings.bot_webhook_token
            payload["attachments"] = [
                {
                    "id": str(a.id),
                    "file_name": a.file_name,
                    "mime_type": a.mime_type,
                    "size_bytes": a.size_bytes,
                    "download_url": (
                        f"{base}/api/v1/integrations/tag/attachments/"
                        f"{a.id}/file?token={token}"
                    ),
                }
                for a in attachments
            ]
        await self._outbox.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=message.id,
            idempotency_key=f"message:{message.id}",
            payload=payload,
        )

    async def _store_attachments(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID | None,
        files: list[IncomingFile],
        uploaded_by_operator_id: uuid.UUID | None = None,
    ) -> list[Any]:
        """Persist attachment rows (and their bytes) for one message."""
        from app.config import get_settings
        from app.errors import ApiError

        max_bytes = get_settings().max_attachment_mb * 1024 * 1024
        stored: list[Any] = []
        for file in files:
            if not file.content:
                continue
            if len(file.content) > max_bytes:
                raise ApiError(
                    code="ATTACHMENT_TOO_LARGE",
                    message=(
                        "Файл больше "
                        f"{get_settings().max_attachment_mb} МБ"
                    ),
                    status_code=413,
                )
            key = await self._storage.save(file.content)
            stored.append(
                await self._attachments.create(
                    session,
                    conversation_id=conversation_id,
                    file_name=file.file_name or "file",
                    mime_type=file.mime_type or "application/octet-stream",
                    size_bytes=len(file.content),
                    storage_key=key,
                    uploaded_by_operator_id=uploaded_by_operator_id,
                )
            )
        for attachment in stored:
            if message_id is not None:
                attachment.message_id = message_id
        return stored

    async def add_operator_upload(
        self,
        session: AsyncSession,
        *,
        ticket_id: uuid.UUID,
        file_name: str,
        mime_type: str,
        content: bytes,
        operator_id: uuid.UUID,
    ) -> Any:
        """Composer upload: store the file now, link it when the reply sends."""
        async with unit_of_work(session):
            ticket = await self._require_ticket(session, ticket_id)
            stored = await self._store_attachments(
                session,
                conversation_id=ticket.conversation_id,
                message_id=None,
                files=[
                    IncomingFile(
                        file_name=file_name, mime_type=mime_type, content=content
                    )
                ],
                uploaded_by_operator_id=operator_id,
            )
        if not stored:
            raise ValueError("Empty file")
        return stored[0]

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
