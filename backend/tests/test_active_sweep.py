"""Owner bug report (2026-11-23): with every operator offline a new chat
lands unassigned and stays there even after the only operator goes ACTIVE.
Going ACTIVE must sweep the unassigned queue."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.infra.redis_client import RedisClient
from app.main import create_app
from app.models import Channel, Conversation, Operator, Ticket, User
from tests.conftest import TEST_DB_URL

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
    redis = RedisClient("redis://127.0.0.1:6379/0")
    deps = Dependencies(db=db, redis=redis)  # type: ignore[arg-type]
    yield deps
    asyncio.run(db.close())
    asyncio.run(redis.close())


@pytest.fixture
def client(operator_env, api_deps) -> TestClient:
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


def _engine():
    return async_sessionmaker(
        create_async_engine(TEST_DB_URL), expire_on_commit=False
    )


def test_going_active_sweeps_unassigned_queue(client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:6]
    login = f"solo{suffix}"

    async def _seed() -> uuid.UUID:
        factory = _engine()
        try:
            async with factory() as session:
                solo = Operator(
                    email=f"{login}@local.test",
                    display_name="Solo",
                    is_active=True,
                    presence_status="OFFLINE",
                    max_active_tickets=5,
                )
                session.add(solo)
                await session.flush()
                channel = Channel(
                    channel_type="tag",
                    external_channel_id=f"chan-{uuid.uuid4().hex[:8]}",
                    display_name="seed",
                )
                session.add(channel)
                user = User(display_name="U3")
                session.add(user)
                await session.flush()
                conversation = Conversation(user_id=user.id, channel_id=channel.id)
                session.add(conversation)
                await session.flush()
                ticket = Ticket(conversation_id=conversation.id, user_id=user.id)
                ticket.created_at = datetime.now(UTC) - timedelta(minutes=5)
                session.add(ticket)
                await session.flush()
                # Isolate: nobody else participates in routing.
                await session.execute(
                    update(Operator)
                    .where(Operator.id != solo.id)
                    .values(max_active_tickets=0)
                )
                await session.execute(
                    update(Ticket)
                    .where(Ticket.id != ticket.id)
                    .values(status="RESOLVED")
                )
                await session.commit()
                return ticket.id
        finally:
            factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]

    async def _assignee(ticket_id: uuid.UUID) -> str | None:
        factory = _engine()
        try:
            async with factory() as session:
                ticket = await session.get(Ticket, ticket_id)
                assert ticket is not None
                if ticket.assignee_id is None:
                    return None
                operator = await session.get(Operator, ticket.assignee_id)
                return str(operator.email) if operator else None
        finally:
            factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]

    ticket_id = asyncio.run(_seed())
    # While everyone is offline the chat waits in the queue.
    assert asyncio.run(_assignee(ticket_id)) is None

    session = client.post("/api/v1/operator/auth/session", auth=(login, TOKEN))
    assert session.status_code == 201
    token = session.json()["session_token"]
    went_active = client.post(
        "/api/v1/operator/presence",
        json={"status": "ACTIVE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert went_active.status_code == 200

    # The fix: going ACTIVE routes the waiting chat to this operator.
    assert asyncio.run(_assignee(ticket_id)) == f"{login}@local.test"
