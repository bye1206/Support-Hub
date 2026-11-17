"""Deferred (capacity-aware) manual assignment (owner rule, stage 9).

Assigning a ticket to an operator at their max_active_tickets queues it
(pending_assignee_id); it lands on them as soon as a slot frees up
(resolve/close/unassign trigger the delivery, oldest first).
"""

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


async def _seed_capacity_pair() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Operator with max_active=1, one open ticket assigned to them and one
    unassigned ticket. Returns (operator_id, busy_ticket_id, free_ticket_id)."""
    factory = _engine()
    try:
        async with factory() as session:
            operator = Operator(
                email=f"cap-{uuid.uuid4().hex[:8]}@corp.test",
                display_name="Capacity Op",
                is_active=True,
                max_active_tickets=1,
            )
            session.add(operator)
            await session.flush()
            channel = Channel(
                channel_type="tag",
                external_channel_id=f"chan-{uuid.uuid4().hex[:8]}",
                display_name="seed",
            )
            session.add(channel)
            user = User(display_name="Capacity User")
            session.add(user)
            await session.flush()
            tickets: list[Ticket] = []
            for _ in range(2):
                conversation = Conversation(user_id=user.id, channel_id=channel.id)
                session.add(conversation)
                await session.flush()
                ticket = Ticket(
                    conversation_id=conversation.id, user_id=user.id
                )
                session.add(ticket)
                tickets.append(ticket)
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        sequence_no=1,
                        author_type=MessageAuthorType.USER,
                        author_user_id=user.id,
                        text="seed",
                    )
                )
            await session.flush()
            tickets[0].assignee_id = operator.id
            await session.commit()
            return operator.id, tickets[0].id, tickets[1].id
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _ticket_state(
    ticket_id: uuid.UUID,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    factory = _engine()
    try:
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            return ticket.assignee_id, ticket.pending_assignee_id
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


def test_assign_to_full_operator_is_queued(client: TestClient) -> None:
    operator_id, _busy, free = asyncio.run(_seed_capacity_pair())

    response = client.post(
        f"/api/v1/operator/tickets/{free}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deferred"] is True
    assert body["pending_assignee_id"] == str(operator_id)

    assignee, pending = asyncio.run(_ticket_state(free))
    assert assignee is None  # stays out of the full operator's hands
    assert pending == operator_id


def test_queued_ticket_lands_when_slot_frees(client: TestClient) -> None:
    operator_id, busy, free = asyncio.run(_seed_capacity_pair())

    queued = client.post(
        f"/api/v1/operator/tickets/{free}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert queued.status_code == 200

    resolved = client.post(
        f"/api/v1/operator/tickets/{busy}/resolve", headers=headers()
    )
    assert resolved.status_code == 200

    assignee, pending = asyncio.run(_ticket_state(free))
    assert assignee == operator_id
    assert pending is None


def test_unassign_also_frees_the_slot(client: TestClient) -> None:
    operator_id, busy, free = asyncio.run(_seed_capacity_pair())

    queued = client.post(
        f"/api/v1/operator/tickets/{free}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert queued.status_code == 200

    unassigned = client.post(
        f"/api/v1/operator/tickets/{busy}/assign",
        json={"assignee_id": None},
        headers=headers(),
    )
    assert unassigned.status_code == 200

    assignee, pending = asyncio.run(_ticket_state(free))
    assert assignee == operator_id
    assert pending is None
