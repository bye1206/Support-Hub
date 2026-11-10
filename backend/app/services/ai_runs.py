"""AI orchestration (stage 6, D-043): one gateway roundtrip per user message.

Flow: a user message in an AI dialog moves the ticket to AI_PROCESSING
(MessageService); the trigger event lands in the outbox; the worker's
fallback enqueues `process_ai_runs`, which registers (dedup) a run and
executes it against the RAG Assistant Gateway SYNCHRONOUSLY (30-60 s).

Run lifecycle and failure policy (D-043, Q-04): the gateway has no
idempotency, so a failed run is NEVER auto-retried - a repeated POST would
create a second LLM message on their side. The run is FAILED, the ticket
stays AI_PROCESSING; the operator or the user's next message unblocks the
dialog.

Trigger codes (D-043 §7): `resolved` closes the ticket (no message is
published), `operator` hands the dialog to a human (D-014: no way back to
AI). Unknown code-like answers are rendered as text (see triggers.py).
"""

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.domain.exceptions import StateConflict, TransitionNotAllowed
from app.domain.state_machines import DialogTrigger, TicketTrigger, next_dialog_mode
from app.integrations.ai.gateway_client import (
    AssistantGatewayClient,
    GatewayAnswer,
    GatewayError,
)
from app.integrations.ai.triggers import TriggerKind, detect_trigger
from app.models import (
    AiProcessingRun,
    AiRunStatus,
    AuditActorType,
    Conversation,
    DialogMode,
    HandoffReason,
    Message,
    MessageAuthorType,
    Ticket,
)
from app.repositories.ai_runs import AiHandoffRepository, AiRunRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.tickets import TicketRepository
from app.services.audit import AuditService
from app.services.messages import MessageService

logger = logging.getLogger(__name__)


class GatewayProtocol(Protocol):
    async def create_chat(self, *, title: str, x_user_id: str) -> int: ...

    async def send_message(
        self, *, chat_id: int, query: str, x_user_id: str
    ) -> GatewayAnswer: ...


def build_gateway_from_settings() -> AssistantGatewayClient:
    settings = get_settings()
    return AssistantGatewayClient(
        base_url=settings.ai_gateway_base_url,
        api_key=settings.ai_gateway_api_key,
        timeout_seconds=settings.ai_gateway_timeout_seconds,
    )


class AiRunService:
    def __init__(
        self,
        gateway: GatewayProtocol | None = None,
        runs: AiRunRepository | None = None,
        handoffs: AiHandoffRepository | None = None,
        conversations: ConversationRepository | None = None,
        messages: MessageRepository | None = None,
        message_service: MessageService | None = None,
        tickets: TicketRepository | None = None,
    ) -> None:
        self._gateway = gateway
        self._runs = runs or AiRunRepository()
        self._handoffs = handoffs or AiHandoffRepository()
        self._conversations = conversations or ConversationRepository()
        self._messages = messages or MessageRepository()
        self._message_service = message_service or MessageService()
        self._tickets = tickets or TicketRepository()

    # --- registration -------------------------------------------------

    async def register_run(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        message: Message,
    ) -> AiProcessingRun | None:
        """Create the run for one user message, inside the caller's transaction.

        Only USER messages in AI_ACTIVE dialogs are processed by the AI;
        anything else (operator dialogue, closed dialog) returns None. A
        re-delivered trigger dedups to None (UNIQUE input+attempt)."""
        if conversation.mode != DialogMode.AI_ACTIVE:
            return None
        if message.author_type != MessageAuthorType.USER:
            return None
        return await self._runs.register(
            session,
            conversation_id=conversation.id,
            input_message_id=message.id,
            request_id=uuid.uuid4(),
        )

    async def ensure_run_for_message(
        self, session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Worker fallback entry: register the run for an ingested message.

        Separate transaction (the ingress transaction is long committed).
        Returns the dialog id when a NEW run is ready for processing."""
        async with session_factory() as session:
            message = await session.get(Message, message_id)
            if message is None:
                logger.warning("AI trigger for missing message %s", message_id)
                return None
            conversation = await self._conversations.get(session, message.conversation_id)
            if conversation is None:
                return None
            run = await self.register_run(session, conversation=conversation, message=message)
            if run is None:
                return None
            await session.commit()
            return conversation.id

    # --- processing ---------------------------------------------------

    async def process_pending(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        limit: int = 10,
    ) -> int:
        """Worker entry: process pending runs, at most one per dialog.

        The HTTP call happens OUTSIDE any DB transaction (30-60 s per the
        contract §5); only claim/apply are transactional."""
        async with session_factory() as session:
            conversation_ids = await self._runs.pending_conversation_ids(
                session, limit=limit
            )
            await session.commit()
        processed = 0
        for conversation_id in conversation_ids:
            processed += await self._process_conversation(session_factory, conversation_id)
        return processed

    async def _process_conversation(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        conversation_id: uuid.UUID,
    ) -> int:
        # Tx 1: claim the run and gather everything the call needs.
        async with session_factory() as session:
            run = await self._runs.claim_next_pending(
                session, conversation_id=conversation_id
            )
            if run is None:
                return 0
            conversation = await self._conversations.get(session, conversation_id)
            input_message = await self._messages.get(session, run.input_message_id)
            if conversation is None or input_message is None:
                await self._runs.mark_failed(
                    session, run, error="conversation or input message disappeared"
                )
                await session.commit()
                return 1
            user_id = conversation.user_id
            query = input_message.text
            cached_chat_id = conversation.ai_chat_id
            run_id = run.id
            await session.commit()

        gateway = self._gateway or build_gateway_from_settings()
        # Outside tx: no idempotency on their side, no retries (D-043).
        try:
            chat_id = cached_chat_id
            if chat_id is None:
                chat_id = await gateway.create_chat(
                    title=f"Support Hub dialog {conversation_id}",
                    x_user_id=str(user_id),
                )
            answer = await gateway.send_message(
                chat_id=chat_id, query=query, x_user_id=str(user_id)
            )
        except GatewayError as exc:
            async with session_factory() as session:
                run = await self._runs.get(session, run_id)
                if run is not None and run.status == AiRunStatus.RUNNING:
                    await self._runs.mark_failed(session, run, error=str(exc))
                    await session.commit()
            logger.warning(
                "AI run failed (no retry, D-043): conversation=%s error=%s",
                conversation_id,
                exc,
            )
            return 1

        async with session_factory() as session:
            try:
                await self._apply_answer(
                    session, run_id=run_id, answer=answer, chat_id=chat_id
                )
                await session.commit()
            except Exception as exc:
                # Unexpected apply failure (e.g. concurrent operator action):
                # the run is terminal, the ticket stays AI_PROCESSING.
                await session.rollback()
                await self._fail_run_quietly(session_factory, run_id, str(exc))
                logger.exception("AI run apply failed: conversation=%s", conversation_id)
            return 1

    async def _fail_run_quietly(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        run_id: uuid.UUID,
        error: str,
    ) -> None:
        """Best-effort terminal marking; never raises (worker context)."""
        try:
            async with session_factory() as session:
                run = await self._runs.get(session, run_id)
                if run is not None and run.status == AiRunStatus.RUNNING:
                    await self._runs.mark_failed(session, run, error=error)
                    await session.commit()
        except Exception:
            logger.exception("Failed to mark run %s FAILED", run_id)

    async def _apply_answer(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
        answer: GatewayAnswer,
        chat_id: int,
    ) -> None:
        """Apply the finished gateway answer in one transaction."""
        run = await self._runs.get(session, run_id)
        if run is None or run.status != AiRunStatus.RUNNING:
            return  # cancelled/failed elsewhere - nothing to publish
        conversation = await self._conversations.get(session, run.conversation_id)
        if conversation is None or conversation.mode != DialogMode.AI_ACTIVE:
            # The dialog left AI mode while we waited (operator/close, D-014).
            await self._runs.mark_cancelled(session, run)
            return
        # Cache the gateway chat id on the dialog (one dialog = one chat).
        if conversation.ai_chat_id is None:
            await self._conversations.set_ai_chat_id(
                session, conversation.id, chat_id=chat_id
            )

        trigger = detect_trigger(answer.answer)
        if trigger == TriggerKind.RESOLVED:
            await self._apply_resolved(session, run, conversation, chat_id)
            return
        if trigger == TriggerKind.OPERATOR:
            try:
                await self._apply_handoff(session, run, conversation, chat_id)
            except StateConflict:
                # The operator claimed the dialog while we waited (D-014).
                await session.rollback()
                await self._runs.mark_cancelled(session, run)
            return

        # Normal answer: publish as an AI message (FSM AI_REPLY -> OPEN).
        try:
            result = await self._message_service.publish_ai_answer(
                session, conversation_id=conversation.id, text=answer.answer
            )
        except TransitionNotAllowed:
            await self._runs.mark_cancelled(session, run)
            return
        await self._runs.mark_succeeded(
            session,
            run,
            response_message_id=result.message.id,
            external_chat_id=chat_id,
        )

    async def _apply_resolved(
        self,
        session: AsyncSession,
        run: AiProcessingRun,
        conversation: Conversation,
        chat_id: int,
    ) -> None:
        """Trigger `resolved`: the user confirmed the problem is solved.

        No message is published (the code is not user-facing); the ticket
        goes to RESOLVED, the dialog stays AI_ACTIVE (the next user message
        reopens it into the AI flow, D-010 via the user-message matrix)."""
        ticket = await self._require_ticket(session, conversation.id)
        await self._message_service.apply_ticket_trigger(
            session, ticket, TicketTrigger.AI_RESOLVED
        )
        await self._runs.cancel_pending_for_conversation(
            session, conversation_id=conversation.id
        )
        await self._runs.mark_succeeded(
            session,
            run,
            trigger_code=get_settings().ai_trigger_resolved_code,
            external_chat_id=chat_id,
        )
        await self._audit_handoff_or_resolve(
            session, conversation.id, action="ai.resolved", run_id=run.id
        )

    async def _apply_handoff(
        self,
        session: AsyncSession,
        run: AiProcessingRun,
        conversation: Conversation,
        chat_id: int,
    ) -> None:
        """Trigger `operator`: the dialog goes to a human (D-014, one way).

        Dialog -> HUMAN_PENDING (an operator claims it, stage 7 UI); ticket
        -> OPEN; an open handoff record waits for acceptance."""
        new_mode = next_dialog_mode(
            str(conversation.mode), DialogTrigger.HUMAN_HANDOFF
        )
        await self._conversations.change_mode(
            session,
            conversation.id,
            from_mode=conversation.mode,
            to_mode=DialogMode(new_mode),
            expected_state_version=conversation.state_version,
        )
        await self._handoffs.create(
            session,
            conversation_id=conversation.id,
            run_id=run.id,
            reason=HandoffReason.OPERATOR_TRIGGER,
            is_accepted=False,
        )
        ticket = await self._require_ticket(session, conversation.id)
        await self._message_service.apply_ticket_trigger(
            session, ticket, TicketTrigger.AI_REQUESTED_HANDOFF
        )
        await self._runs.cancel_pending_for_conversation(
            session, conversation_id=conversation.id
        )
        await self._runs.mark_succeeded(
            session,
            run,
            trigger_code=get_settings().ai_trigger_operator_code,
            external_chat_id=chat_id,
        )
        await self._audit_handoff_or_resolve(
            session, conversation.id, action="ai.handoff_requested", run_id=run.id
        )

    async def _require_ticket(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Ticket:
        ticket = await self._tickets.get_by_conversation(session, conversation_id)
        if ticket is None:
            raise ValueError(f"No ticket for conversation {conversation_id}")
        return ticket

    async def _audit_handoff_or_resolve(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        action: str,
        run_id: uuid.UUID,
    ) -> None:
        await AuditService().log(
            session,
            actor_type=AuditActorType.AI,
            action=action,
            entity_type="conversation",
            entity_id=conversation_id,
            details={"run_id": str(run_id)},
        )
