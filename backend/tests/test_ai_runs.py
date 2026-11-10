"""Integration tests of the AI orchestration flow on real PostgreSQL (stage 6).

Covers the D-043 contract end to end with a fake gateway (the real client is
unit-tested against MockTransport separately):
- happy path: user message -> run -> AI answer published (ticket -> OPEN);
- operator trigger: dialog -> HUMAN_PENDING + handoff (no AI message);
- resolved trigger: ticket -> RESOLVED (no AI message);
- gateway 503: run FAILED (no retry), ticket stays AI_PROCESSING (Q-04);
- run dedup (at-least-once trigger events);
- CANCELLED: the dialog left AI mode while the answer was in flight;
- worker fallback: message.user_received enqueues process_ai_runs.
"""

import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.integrations.ai.gateway_client import GatewayAnswer, GatewayUnavailable
from app.models import (
    AiHandoff,
    AiProcessingRun,
    AiRunStatus,
    Conversation,
    DialogMode,
    Message,
    MessageAuthorType,
    OutboxEvent,
    Ticket,
    TicketStatus,
)
from app.services.ai_runs import AiRunService
from app.services.messages import MessageService
from app.worker.tasks import _outbox_handler, process_ai_runs  # noqa: SLF001

USER_ID = "tag-user-fixed-1"


class FakeGateway:
    """Scripted gateway: pops answers/exceptions per send_message call."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers) or ["Ответ ИИ"]
        self.chat_creations = 0
        self.sent: list[dict] = []

    async def create_chat(self, *, title: str, x_user_id: str) -> int:
        self.chat_creations += 1
        return 1000 + self.chat_creations

    async def send_message(
        self, *, chat_id: int, query: str, x_user_id: str
    ) -> GatewayAnswer:
        self.sent.append(
            {"chat_id": chat_id, "query": query, "x_user_id": x_user_id}
        )
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return GatewayAnswer(answer=str(item))


async def _seed_user_message(
    session_factory, *, external_user_id: str = USER_ID, text: str = "Не работает VPN"
) -> tuple[uuid.UUID, uuid.UUID]:
    """One user message through the real ingress flow; returns (message_id,
    conversation_id). The same user keeps the same dialog (P-04 routing)."""
    service = MessageService()
    async with session_factory() as session:
        result = await service.handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=external_user_id,
            external_user_name="Тестовый Пользователь",
            text=text,
            external_post_id=f"post-{uuid.uuid4().hex[:8]}",
        )
        await session.commit()
        return result.message.id, result.conversation.id


async def _get_run(session_factory, message_id: uuid.UUID) -> AiProcessingRun:
    async with session_factory() as session:
        stmt = select(AiProcessingRun).where(
            AiProcessingRun.input_message_id == message_id
        )
        return (await session.scalars(stmt)).one()


async def _get_ticket(session_factory, conversation_id: uuid.UUID) -> Ticket:
    async with session_factory() as session:
        stmt = select(Ticket).where(Ticket.conversation_id == conversation_id)
        return (await session.scalars(stmt)).one()


@pytest.mark.anyio
async def test_happy_path_publishes_ai_answer_and_opens_ticket(session_factory) -> None:
    message_id, conversation_id = await _seed_user_message(session_factory)
    gateway = FakeGateway("Проверьте подключение и перезагрузите роутер")
    service = AiRunService(gateway=gateway)

    registered = await service.ensure_run_for_message(session_factory, message_id)
    assert registered == conversation_id
    processed = await service.process_pending(session_factory)
    assert processed == 1

    # The run succeeded and points at the published AI message.
    run = await _get_run(session_factory, message_id)
    assert run.status == AiRunStatus.SUCCEEDED
    assert run.trigger_code is None
    assert run.response_message_id is not None
    assert run.external_chat_id == 1001
    # The gateway got exactly one chat and one message; X-User-Id = our UUID.
    assert gateway.chat_creations == 1
    assert len(gateway.sent) == 1
    assert gateway.sent[0]["query"] == "Не работает VPN"

    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.ai_chat_id == 1001
        messages = list(
            (
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            ).all()
        )
        assert len(messages) == 2  # user + AI
        ai_message = [m for m in messages if m.author_type == MessageAuthorType.AI][0]
        assert ai_message.id == run.response_message_id
        assert ai_message.text == "Проверьте подключение и перезагрузите роутер"

    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.OPEN  # AI_REPLY completes processing

    # Outbound delivery event for the AI message is registered.
    async with session_factory() as session:
        outbound = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "message.outbound"
                    )
                )
            ).all()
        )
        assert len(outbound) == 1


@pytest.mark.anyio
async def test_second_message_reuses_cached_gateway_chat(session_factory) -> None:
    """One dialog = one gateway chat (D-043): the second user message in the
    same dialog goes to the SAME chat id without creating a new one."""
    gateway = FakeGateway("Ответ 1", "Ответ 2")
    service_with_gateway = AiRunService(gateway=gateway)

    first_id, conversation_id = await _seed_user_message(session_factory)
    await service_with_gateway.ensure_run_for_message(session_factory, first_id)
    await service_with_gateway.process_pending(session_factory)

    second_id, same_conversation = await _seed_user_message(
        session_factory, text="Второй вопрос"
    )
    assert same_conversation == conversation_id  # P-04: same user's dialog
    await service_with_gateway.ensure_run_for_message(session_factory, second_id)
    await service_with_gateway.process_pending(session_factory)

    assert gateway.chat_creations == 1  # reused for the whole dialog
    assert [s["chat_id"] for s in gateway.sent] == [1001, 1001]

    run2 = await _get_run(session_factory, second_id)
    assert run2.status == AiRunStatus.SUCCEEDED
    assert run2.external_chat_id == 1001


@pytest.mark.anyio
async def test_operator_trigger_hands_dialog_to_human(session_factory) -> None:
    message_id, conversation_id = await _seed_user_message(session_factory)
    operator_code = get_settings().ai_trigger_operator_code
    gateway = FakeGateway(operator_code)
    service = AiRunService(gateway=gateway)
    await service.ensure_run_for_message(session_factory, message_id)
    await service.process_pending(session_factory)

    run = await _get_run(session_factory, message_id)
    assert run.status == AiRunStatus.SUCCEEDED
    assert run.trigger_code == operator_code
    assert run.response_message_id is None  # no AI message for trigger codes

    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.OPEN  # AI_REQUESTED_HANDOFF target

    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.mode == DialogMode.HUMAN_PENDING
        handoffs = list((await session.scalars(select(AiHandoff))).all())
        assert len(handoffs) == 1
        assert handoffs[0].conversation_id == conversation_id
        assert handoffs[0].run_id == run.id
        assert handoffs[0].is_accepted is False
        assert handoffs[0].reason == "OPERATOR_TRIGGER"


@pytest.mark.anyio
async def test_resolved_trigger_resolves_ticket_without_message(session_factory) -> None:
    message_id, conversation_id = await _seed_user_message(session_factory)
    resolved_code = get_settings().ai_trigger_resolved_code
    gateway = FakeGateway(resolved_code)
    service = AiRunService(gateway=gateway)
    await service.ensure_run_for_message(session_factory, message_id)
    await service.process_pending(session_factory)

    run = await _get_run(session_factory, message_id)
    assert run.status == AiRunStatus.SUCCEEDED
    assert run.trigger_code == resolved_code

    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.RESOLVED

    async with session_factory() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            ).all()
        )
        assert len(messages) == 1  # the user message only


@pytest.mark.anyio
async def test_gateway_503_fails_run_ticket_stays_ai_processing(session_factory) -> None:
    message_id, conversation_id = await _seed_user_message(session_factory)
    gateway = FakeGateway(GatewayUnavailable("Gateway answered 503"))
    service = AiRunService(gateway=gateway)
    await service.ensure_run_for_message(session_factory, message_id)
    processed = await service.process_pending(session_factory)

    assert processed == 1
    run = await _get_run(session_factory, message_id)
    assert run.status == AiRunStatus.FAILED
    assert "503" in (run.error or "")
    assert run.response_message_id is None

    # Q-04 (D-043): no retries; the operator/next user message unblocks.
    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.AI_PROCESSING

    async with session_factory() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            ).all()
        )
        assert len(messages) == 1  # nothing published


@pytest.mark.anyio
async def test_trigger_event_redelivery_does_not_create_second_run(session_factory) -> None:
    message_id, _ = await _seed_user_message(session_factory)
    gateway = FakeGateway("Ответ ИИ")
    service = AiRunService(gateway=gateway)

    first = await service.ensure_run_for_message(session_factory, message_id)
    second = await service.ensure_run_for_message(session_factory, message_id)
    assert first is not None and second is None  # dedup

    processed = await service.process_pending(session_factory)
    assert processed == 1
    async with session_factory() as session:
        runs = len(
            list(
                (
                    await session.scalars(
                        select(AiProcessingRun).where(
                            AiProcessingRun.input_message_id == message_id
                        )
                    )
                ).all()
            )
        )
    assert runs == 1


@pytest.mark.anyio
async def test_dialog_left_ai_mode_run_is_cancelled(session_factory) -> None:
    message_id, conversation_id = await _seed_user_message(session_factory)
    gateway = FakeGateway("Поздний ответ ИИ")
    service = AiRunService(gateway=gateway)
    registered = await service.ensure_run_for_message(session_factory, message_id)
    assert registered is not None

    # The operator preempts the AI while the run waits in the queue (D-011).
    ticket = await _get_ticket(session_factory, conversation_id)
    message_service = MessageService()
    async with session_factory() as session:
        await message_service.add_operator_reply(
            session, ticket_id=ticket.id, text="Оператор подключился"
        )
        await session.commit()

    await service.process_pending(session_factory)
    run = await _get_run(session_factory, message_id)
    assert run.status == AiRunStatus.CANCELLED

    async with session_factory() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            ).all()
        )
        assert "Поздний ответ ИИ" not in [m.text for m in messages]


@pytest.mark.anyio
async def test_worker_fallback_enqueues_process_ai_runs(session_factory) -> None:
    message_id, _ = await _seed_user_message(session_factory)

    class FakeRedis:
        def __init__(self) -> None:
            self.jobs: list[tuple[str, tuple]] = []

        async def enqueue_job(self, name: str, *args) -> None:
            self.jobs.append((name, args))

    redis = FakeRedis()
    handler = _outbox_handler({"redis": redis})
    event = OutboxEvent(
        event_type="message.user_received",
        aggregate_type="message",
        aggregate_id=message_id,
        idempotency_key=f"message:{message_id}",
        payload={
            "message_id": str(message_id),
            "conversation_id": str(uuid.uuid4()),
        },
    )
    await handler(event)
    assert redis.jobs == [("process_ai_runs", (str(message_id),))]


@pytest.mark.anyio
async def test_process_ai_runs_task_end_to_end(session_factory) -> None:
    """The ARQ task itself: ensure + process in one call (wiring check)."""
    message_id, conversation_id = await _seed_user_message(session_factory)
    gateway = FakeGateway("Ответ через задачу")
    ctx = {"session_factory": session_factory, "ai_gateway": gateway}
    processed = await process_ai_runs(ctx, str(message_id))
    assert processed == 1

    ticket = await _get_ticket(session_factory, conversation_id)
    assert ticket.status == TicketStatus.OPEN
