"""Ticket lifecycle: P-04 routing, resolve/close (D-010 revised: terminal), dialog mode."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    Message,
    MessageAuthorType,
    MessageDeliveryState,
    Tag,
    Ticket,
    TicketHistoryKind,
    TicketStatus,
)
from app.repositories.ai_runs import AiHandoffRepository
from app.repositories.categories import TicketCategoryRepository
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.operators import OperatorRepository
from app.repositories.tags import TagRepository
from app.repositories.tickets import TicketRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService
from app.services.outbox import OutboxService
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)


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
        self._messages = MessageRepository()
        self._sessions = sessions or SessionService()
        self._audit = audit or AuditService()
        self._operators = operators or OperatorRepository()
        self._handoffs = handoffs or AiHandoffRepository()
        self._categories = categories or TicketCategoryRepository()
        self._tags = tags or TagRepository()
        self._channels = channels or ChannelRepository()
        self._outbox = OutboxService()

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
            # Owner flow (2026-11-13): a NEW dialog belongs to the AI first
            # (greeting -> question -> AI answer). Operators take over only
            # via the handoff key / the distribution panel — never at birth.
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

        # Owner rule (2026-11-17): a dialog cannot outlive its 3-hour session.
        # If the dialog's session is gone (worker missed it or the message
        # raced the sweep), the timeout closes the old ticket here and the
        # user's message opens a fresh dialog with a fresh ticket below.
        if not await self._sessions.has_live_session(
            session, existing_conversation.id
        ):
            await self.close_on_timeout(session, last.id)
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
                details={
                    "conversation_id": str(conversation.id),
                    "after": "session_timeout",
                },
            )
            await self._auto_tag_from_channel(session, ticket, channel_id)
            return RoutingResult(
                conversation=conversation,
                ticket=ticket,
                conversation_created=True,
                ticket_reopened=False,
            )

        return RoutingResult(
            conversation=existing_conversation,
            ticket=last,
            conversation_created=False,
            ticket_reopened=False,
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
            # Owner request (2026-11-19): the closure invites the user to
            # rate the dialog; the score is attributed to the operator.
            await self._notify_resolution(
                session,
                ticket.conversation_id,
                rating_target="OPERATOR",
                rating_operator_id=actor_id or ticket.assignee_id,
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.resolved",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
            )
            if ticket.assignee_id:
                await self._apply_pending(session, ticket.assignee_id)
            await self._auto_route_queue(session)
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
            if ticket.assignee_id:
                await self._apply_pending(session, ticket.assignee_id)
            await self._auto_route_queue(session)
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
            # Owner request (2026-11-19): the status history feeds the SLA
            # modal (per-status durations).
            await self._tickets.add_history(
                session,
                ticket_id=ticket_id,
                kind=TicketHistoryKind.STATUS,
                from_status=str(ticket.status),
                to_status=str(target),
            )
            await session.refresh(ticket)
        # Owner request (2026-11-19): the 15-minute reply SLA.
        if trigger == TicketTrigger.OPERATOR_CLAIM:
            from datetime import UTC, datetime, timedelta

            await self._tickets.set_sla_deadline(
                session,
                ticket_id,
                deadline=datetime.now(UTC) + timedelta(minutes=15),
            )
        elif trigger in (
            TicketTrigger.OPERATOR_RESOLVED,
            TicketTrigger.OPERATOR_CLOSED,
            TicketTrigger.SESSION_TIMEOUT,
        ):
            # Terminal: no more operator replies — stop the clock silently.
            await self._tickets.clear_sla(session, ticket_id)
        return ticket

    async def send_resolution_note(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        rating_target: str = "OPERATOR",
        rating_operator_id: uuid.UUID | None = None,
    ) -> None:
        """Public wrapper: the farewell note to the user (operator resolve
        and the AI "помогло" key both end a dialog with it)."""
        await self._notify_resolution(
            session,
            conversation_id,
            rating_target=rating_target,
            rating_operator_id=rating_operator_id,
        )

    async def route_unassigned(self, session: AsyncSession) -> int:
        """Public wrapper: hand unassigned human tickets to free ACTIVE
        operators (owner flow step 9 after the AI handoff key)."""
        return await self._auto_route_queue(session)

    async def _notify_assignment(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> None:
        """System message telling the user an operator took the chat.
        Owner request 2026-11-13: the note must reach the user in Tag, so it
        goes through the outbound outbox like any operator reply.
        Owner request (2026-11-23): no operator name in the text, and the
        note goes ONCE per conversation — reassignments stay silent."""
        text = (
            "Оператор назначен. "
            "Он изучит проблему и поможет в ближайшее время."
        )
        already = await session.scalar(
            select(Message.id).where(
                Message.conversation_id == conversation_id,
                Message.author_type == MessageAuthorType.SYSTEM,
                Message.text == text,
            )
        )
        if already is not None:
            return
        message = await self._create_system_message(
            session,
            conversation_id,
            text,
        )
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

    async def _notify_resolution(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        rating_target: str | None = None,
        rating_operator_id: uuid.UUID | None = None,
    ) -> None:
        """Owner request 2026-11-13: on resolve the user gets a farewell
        note, delivered to Tag through the outbound outbox.

        Owner request 2026-11-19: the note asks for a 1-5 rating (buttons
        in direct mode). The attribution target is stamped on the ticket so
        whichever way the score arrives (button click or a digit reply) it
        reaches the AI or the operator who closed the dialog."""
        text = "Диалог со специалистом завершен!\nСпасибо за обращение в техподдержку! 🙌"
        payload: dict[str, Any] = {
            "message_id": "",
            "conversation_id": str(conversation_id),
        }
        if rating_target:
            ticket = await self._tickets.get_by_conversation(session, conversation_id)
            if ticket is not None:
                ticket.rating_target = rating_target
                ticket.rating_operator_id = rating_operator_id
                payload["ticket_id"] = str(ticket.id)
            text += "\nПоставьте, пожалуйста, оценку от 1 до 5:"
            payload["rating_request"] = True
        message = await self._create_system_message(
            session,
            conversation_id,
            text,
        )
        payload["message_id"] = str(message.id)
        await self._outbox.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=message.id,
            idempotency_key=f"message:{message.id}",
            payload=payload,
        )

    TIMEOUT_FAREWELL_TEXT = (
        "Диалог закрыт: время сессии ограничено (3 часа).\n"
        "Если проблема не решена — напишите повторно, мы продолжим работу."
    )
    TIMEOUT_OPERATOR_NOTE = (
        "Сессия завершена по таймауту (3 часа). Диалог закрыт и убран из очереди."
    )

    async def close_on_timeout(self, session: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
        """Owner rule (2026-11-17): the 3-hour session timeout closes the
        ticket and the dialog. The user gets a farewell note in Tag (outbox);
        the operator sees a system note in the dialog history and the dialog
        leaves their queue. Terminal: no reopen, the user's next message
        starts a new ticket. Caller's transaction."""
        ticket = await self._tickets.get(session, ticket_id)
        if ticket is None:
            raise StateConflict(f"Ticket {ticket_id} not found")
        if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            return None
        ticket = await self._apply_status(session, ticket_id, TicketTrigger.SESSION_TIMEOUT)
        conversation = await self._conversations.get(session, ticket.conversation_id)
        if conversation is not None and conversation.mode != DialogMode.CLOSED:
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
        await self._sessions.end_active(session, ticket.conversation_id)
        # The user-facing farewell goes out through Tag like any reply.
        farewell = await self._create_system_message(
            session, ticket.conversation_id, self.TIMEOUT_FAREWELL_TEXT
        )
        await self._outbox.register(
            session,
            event_type="message.outbound",
            aggregate_type="message",
            aggregate_id=farewell.id,
            idempotency_key=f"message:{farewell.id}",
            payload={
                "message_id": str(farewell.id),
                "conversation_id": str(ticket.conversation_id),
            },
        )
        # The operator-facing note stays in the history only (no outbox).
        await self._create_system_message(
            session, ticket.conversation_id, self.TIMEOUT_OPERATOR_NOTE
        )
        await self._audit.log(
            session,
            actor_type=AuditActorType.SYSTEM,
            action="ticket.timeout_closed",
            entity_type="ticket",
            entity_id=ticket.id,
            details={"conversation_id": str(ticket.conversation_id)},
        )
        if ticket.assignee_id:
            await self._apply_pending(session, ticket.assignee_id)
        return ticket

    async def close_timed_out(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> int:
        """Worker step: close every non-terminal ticket whose dialog has no
        unexpired ACTIVE session. One transaction per ticket; a failure on
        one dialog does not block the rest."""
        now = datetime.now(UTC)
        async with factory() as session:
            ticket_ids = await self._tickets.list_timed_out(session, now=now)
        closed = 0
        for ticket_id in ticket_ids:
            async with factory() as session:
                try:
                    async with unit_of_work(session):
                        if await self.close_on_timeout(session, ticket_id) is not None:
                            closed += 1
                except StateConflict:
                    logger.warning("Timeout close skipped for %s", ticket_id)
        return closed

    async def breach_overdue_slas(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> int:
        """Worker step (owner request 2026-11-19): flag every OPEN ticket
        whose 15-minute reply deadline has passed. The history gets a
        `sla_breached` row and a WS event refreshes the workspace."""
        now = datetime.now(UTC)
        async with factory() as session:
            overdue = await self._tickets.list_overdue_sla(session, now=now)
            breached = 0
            for ticket in overdue:
                marked = await self._tickets.mark_sla_breached(session, ticket.id, at=now)
                if marked:
                    await self._tickets.add_history(
                        session,
                        ticket_id=ticket.id,
                        kind=TicketHistoryKind.SLA_BREACHED,
                    )
                    breached += 1
            await session.commit()
        if breached:
            try:
                from app.config import get_settings
                from app.infra.redis_client import RedisClient

                await RedisClient(get_settings().redis_url).publish_event(
                    '{"type": "tickets.changed"}'
                )
            except Exception:  # noqa: BLE001 - redis trouble must not break the sweep
                logger.warning("SLA breach event not published")
        return breached

    async def create_bot_note(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        text: str,
    ) -> Message:
        """Public system note to the user (rating answers)."""
        return await self._create_system_message(session, conversation_id, text)

    async def _create_system_message(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        text: str,
    ) -> Message:
        sequence = await self._conversations.allocate_sequence(
            session, conversation_id
        )
        return await self._messages.create(
            session,
            conversation_id=conversation_id,
            sequence_no=sequence,
            author_type=MessageAuthorType.SYSTEM,
            delivery_state=MessageDeliveryState.DELIVERED,
            text=text,
        )

    async def assign(
        self,
        session: AsyncSession,
        ticket_id: uuid.UUID,
        *,
        assignee_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> tuple[Ticket, bool]:
        """Manual assignment (docs/06 §6); D-031 auto-assignment stays behind
        a flag (P-07). Owner rule: if the target operator is at capacity the
        ticket is queued (pending_assignee_id) and lands on them as soon as a
        slot frees up. Returns (ticket, deferred). Own transaction."""
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
            previous_assignee = ticket.assignee_id
            deferred = False
            assignee = None
            if assignee_id is not None:
                assignee = await self._operators.get(session, assignee_id)
                if assignee is None:
                    raise ValueError(f"Operator {assignee_id} not found")
                if not assignee.is_active:
                    raise ValueError(f"Operator {assignee_id} is deactivated")
                load = await self._tickets.count_active_for(session, assignee_id)
                # Re-assigning to the same operator or re-queuing is allowed.
                if load >= assignee.max_active_tickets and ticket.assignee_id != assignee_id:
                    await self._tickets.set_pending_assignee(
                        session, ticket_id, pending_assignee_id=assignee_id
                    )
                    await self._audit.log(
                        session,
                        actor_type=AuditActorType.OPERATOR,
                        action="ticket.assignment_queued",
                        entity_type="ticket",
                        entity_id=ticket_id,
                        actor_id=actor_id,
                        details={"assignee_id": str(assignee_id)},
                    )
                    await session.refresh(ticket)
                    return ticket, True
            await self._tickets.set_assignee(
                session, ticket_id, assignee_id=assignee_id
            )
            await self._tickets.set_pending_assignee(
                session, ticket_id, pending_assignee_id=None
            )
            await session.refresh(ticket)
            # Owner rule 2026-11-13: assignment IS a claim — the dialog leaves
            # the AI immediately (no "assigned but still with the AI" state).
            await self._claim_from_ai(session, ticket)
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="ticket.assigned",
                entity_type="ticket",
                entity_id=ticket_id,
                actor_id=actor_id,
                details={"assignee_id": str(assignee_id) if assignee_id else None},
            )
            if assignee is not None:
                await self._notify_assignment(
                    session,
                    ticket.conversation_id,
                )
            # The previous assignee just lost a slot - deliver their queued
            # tickets. The released ticket itself stays in the common queue
            # for manual/auto distribution, it does not bounce back.
            if previous_assignee is not None and previous_assignee != assignee_id:
                await self._apply_pending(session, previous_assignee)
            return ticket, deferred

    async def _claim_from_ai(self, session: AsyncSession, ticket: Ticket) -> None:
        """Pull the dialog out of the AI when an operator takes the ticket:
        AI_ACTIVE -> HUMAN_ACTIVE, AI_PROCESSING -> OPEN. No-op in human
        dialogs. Caller's transaction."""
        conversation = await self._conversations.get(
            session, ticket.conversation_id
        )
        if conversation is None or conversation.mode != DialogMode.AI_ACTIVE:
            return
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
        if ticket.status in (TicketStatus.AI_PROCESSING, TicketStatus.NEW):
            # Owner (2026-11-18): assignment IS "В работе" — including a
            # greeting-stage ticket that never reached AI_PROCESSING yet.
            await self._apply_status(session, ticket.id, TicketTrigger.OPERATOR_CLAIM)

    async def _apply_pending(self, session: AsyncSession, operator_id: uuid.UUID) -> None:
        """Deliver queued tickets to the operator while they have capacity
        (oldest first). Caller's transaction."""
        while True:
            operator = await self._operators.get(session, operator_id)
            if operator is None or not operator.is_active:
                return
            load = await self._tickets.count_active_for(session, operator_id)
            if load >= operator.max_active_tickets:
                return
            pending = await self._tickets.oldest_pending_for(session, operator_id)
            if pending is None:
                return
            await self._tickets.set_assignee(
                session, pending.id, assignee_id=operator_id
            )
            await self._tickets.set_pending_assignee(
                session, pending.id, pending_assignee_id=None
            )
            # Same owner rule as manual assignment: delivery IS a claim.
            await self._claim_from_ai(session, pending)
            await self._audit.log(
                session,
                actor_type=AuditActorType.SYSTEM,
                action="ticket.assigned",
                entity_type="ticket",
                entity_id=pending.id,
                details={
                    "assignee_id": str(operator_id),
                    "deferred_applied": True,
                },
            )
            await self._notify_assignment(
                session, pending.conversation_id
            )

    async def release_operator_tickets(
        self, session: AsyncSession, operator_id: uuid.UUID
    ) -> int:
        """Owner rule: an operator who leaves ACTIVE (lunch/break/offline)
        must not keep chats. Their active tickets return to the queue with
        HIGH priority and are routed to free operators right away; when
        everyone is at capacity they wait and go to the first freed slot.
        Own transaction. Returns the number of released tickets."""
        async with unit_of_work(session):
            tickets = await self._tickets.list_active_for_operator(
                session, operator_id
            )
            for ticket in tickets:
                await self._tickets.set_assignee(
                    session, ticket.id, assignee_id=None
                )
                if ticket.priority == "NORMAL":
                    await self._tickets.set_priority(
                        session, ticket.id, priority="HIGH"
                    )
                await self._audit.log(
                    session,
                    actor_type=AuditActorType.SYSTEM,
                    action="ticket.released",
                    entity_type="ticket",
                    entity_id=ticket.id,
                    details={
                        "operator_id": str(operator_id),
                        "reason": "presence_not_active",
                    },
                )
            await self._auto_route_queue(session)
            return len(tickets)

    async def _auto_route_queue(self, session: AsyncSession) -> int:
        """Hand unassigned active tickets to free ACTIVE operators, highest
        priority first (owner rule); leftovers wait for a freed slot.
        Caller's transaction."""
        assigned = 0
        while True:
            queue = await self._tickets.list_unassigned_active(session)
            if not queue:
                break
            operator = await self._operators.least_loaded_active(session)
            if operator is None:
                break
            ticket = queue[0]
            await self._tickets.set_assignee(
                session, ticket.id, assignee_id=operator.id
            )
            # Same owner rule: delivery IS a claim (AI loses the dialog).
            await self._claim_from_ai(session, ticket)
            await self._audit.log(
                session,
                actor_type=AuditActorType.SYSTEM,
                action="ticket.assigned",
                entity_type="ticket",
                entity_id=ticket.id,
                details={"assignee_id": str(operator.id), "auto": True},
            )
            await self._notify_assignment(session, ticket.conversation_id)
            assigned += 1
        return assigned

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
