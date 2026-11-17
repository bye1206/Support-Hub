"""Owner rule 2026-11-13: manual assignment IS a claim — the dialog leaves
the AI immediately (AI_ACTIVE -> HUMAN_ACTIVE, AI_PROCESSING -> OPEN)."""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.main import create_app
from app.models import (
    Channel,
    Conversation,
    DialogMode,
    Message,
    MessageAuthorType,
    Operator,
    Ticket,
    User,
)
from tests.conftest import TEST_DB_URL
from tests.fakes import FakeProbe

TOKEN = "test-operator-token"


@pytest.fixture
def operator_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPERATOR_DEV_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def api_deps():
    db = DatabaseClient(TEST_DB_URL)
    deps = Dependencies(db=db, redis=FakeProbe())  # type: ignore[arg-type]
    yield deps
    asyncio.run(db.close())


@pytest.fixture
def client(operator_env, api_deps) -> TestClient:
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-Operator-Email": "op1@corp.test",
        "X-Operator-Name": "Operator One",
    }


def _engine():
    return async_sessionmaker(
        create_async_engine(TEST_DB_URL), expire_on_commit=False
    )


async def _seed_ai_ticket() -> tuple[uuid.UUID, uuid.UUID]:
    """Operator + a ticket in the AI dialog (AI_PROCESSING / AI_ACTIVE).
    Returns (operator_id, ticket_id)."""
    factory = _engine()
    try:
        async with factory() as session:
            operator = Operator(
                email=f"claim-{uuid.uuid4().hex[:8]}@corp.test",
                display_name="Claim Op",
                is_active=True,
            )
            session.add(operator)
            await session.flush()
            channel = Channel(
                channel_type="tag",
                external_channel_id=f"chan-{uuid.uuid4().hex[:8]}",
                display_name="seed",
            )
            session.add(channel)
            user = User(display_name="AI User")
            session.add(user)
            await session.flush()
            conversation = Conversation(
                user_id=user.id,
                channel_id=channel.id,
                mode=DialogMode.AI_ACTIVE,
            )
            session.add(conversation)
            await session.flush()
            ticket = Ticket(
                conversation_id=conversation.id,
                user_id=user.id,
                status="AI_PROCESSING",
            )
            session.add(ticket)
            session.add(
                Message(
                    conversation_id=conversation.id,
                    sequence_no=1,
                    author_type=MessageAuthorType.USER,
                    author_user_id=user.id,
                    text="seed",
                )
            )
            await session.commit()
            return operator.id, ticket.id
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _ticket_and_mode(
    ticket_id: uuid.UUID,
) -> tuple[str, str]:
    factory = _engine()
    try:
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            conversation = await session.get(Conversation, ticket.conversation_id)
            assert conversation is not None
            return str(ticket.status), str(conversation.mode)
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


def test_assigning_ai_ticket_claims_it_from_ai(client: TestClient) -> None:
    operator_id, ticket_id = asyncio.run(_seed_ai_ticket())

    response = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert response.status_code == 200

    status, mode = asyncio.run(_ticket_and_mode(ticket_id))
    # Owner rule: a ticket is either with the AI or with an operator.
    assert status == "OPEN"
    assert mode == "HUMAN_ACTIVE"


def test_unassigned_ai_ticket_is_not_auto_routed(client: TestClient) -> None:
    """AI-owned dialogs stay with the AI: auto-routing must not claim them."""
    operator_id, ticket_id = asyncio.run(_seed_ai_ticket())

    # Trigger the routing pass via presence release of an idle operator: the
    # simplest way to hit _auto_route_queue without a real resolve/close.
    response = client.post(
        "/api/v1/operator/presence",
        json={"status": "BREAK"},
        headers=headers(),
    )
    assert response.status_code == 200

    status, mode = asyncio.run(_ticket_and_mode(ticket_id))
    assert status == "AI_PROCESSING"
    assert mode == "AI_ACTIVE"
    del operator_id
