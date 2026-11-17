"""Owner rule: leaving ACTIVE (lunch/break/offline) releases the operator's
active chats to the queue with HIGH priority; free operators pick them up
right away, otherwise the first freed slot does."""

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


def headers(email: str = "op1@corp.test") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-Operator-Email": email,
        "X-Operator-Name": "Operator One",
    }


def _engine():
    return async_sessionmaker(
        create_async_engine(TEST_DB_URL), expire_on_commit=False
    )


async def _seed_scenario() -> tuple[dict[str, uuid.UUID], dict[str, str]]:
    """busy operator (ACTIVE, 1 chat) + free operator; the busy one also has
    a NORMAL-priority chat that must become HIGH when they leave ACTIVE."""
    factory = _engine()
    try:
        async with factory() as session:
            suffix = uuid.uuid4().hex[:6]
            busy = Operator(
                email=f"busy{suffix}@local.test",
                display_name="Busy",
                is_active=True,
                presence_status="ACTIVE",
                max_active_tickets=5,
            )
            free = Operator(
                email=f"free{suffix}@local.test",
                display_name="Free",
                is_active=True,
                presence_status="ACTIVE",
                max_active_tickets=5,
            )
            session.add_all([busy, free])
            await session.flush()
            channel = Channel(
                channel_type="tag",
                external_channel_id=f"chan-{uuid.uuid4().hex[:8]}",
                display_name="seed",
            )
            session.add(channel)
            user = User(display_name="U")
            session.add(user)
            await session.flush()
            ids: dict[str, uuid.UUID] = {"busy": busy.id, "free": free.id}
            logins = {"busy": f"busy{suffix}", "free": f"free{suffix}"}
            # Isolate the scenario: other operators (incl. leftovers from
            # other tests) must not participate in routing.
            await session.execute(
                update(Operator)
                .where(Operator.id.not_in([busy.id, free.id]))
                .values(max_active_tickets=0)
            )
            for index in range(2):
                conversation = Conversation(user_id=user.id, channel_id=channel.id)
                session.add(conversation)
                await session.flush()
                ticket = Ticket(
                    conversation_id=conversation.id,
                    user_id=user.id,
                    assignee_id=busy.id,
                    priority="NORMAL",
                )
                # Distinct timestamps: created_at defaults to the transaction
                # time (identical for both rows), which would leave the
                # routing order to the random id tiebreak.
                ticket.created_at = datetime.now(UTC) - timedelta(minutes=10 - index)
                session.add(ticket)
                await session.flush()
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        sequence_no=1,
                        author_type=MessageAuthorType.USER,
                        author_user_id=user.id,
                        text=f"seed {index}",
                    )
                )
                ids[f"ticket{index}"] = ticket.id
            # Stray unassigned tickets (left by earlier failed runs) must not
            # occupy the auto-routing queue ahead of the scenario's chats.
            await session.execute(
                update(Ticket)
                .where(Ticket.id.not_in([ids["ticket0"], ids["ticket1"]]))
                .values(status="RESOLVED")
            )
            await session.commit()
            return ids, logins
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _ticket_state(
    ticket_id: uuid.UUID,
) -> tuple[str | None, str | None]:
    factory = _engine()
    try:
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            assignee = None
            if ticket.assignee_id is not None:
                operator = await session.get(Operator, ticket.assignee_id)
                assignee = str(operator.email) if operator else None
            return assignee, ticket.priority
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _presence_of(operator_id: uuid.UUID) -> str:
    factory = _engine()
    try:
        async with factory() as session:
            operator = await session.get(Operator, operator_id)
            assert operator is not None
            return str(operator.presence_status)
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


def test_leaving_active_releases_chats_to_free_operator(
    client: TestClient,
) -> None:
    ids, logins = asyncio.run(_seed_scenario())
    # Sign in as the busy operator (dev token) to switch their presence.
    session = client.post(
        "/api/v1/operator/auth/session",
        auth=(logins["busy"], TOKEN),
    )
    assert session.status_code == 201
    token = session.json()["session_token"]

    response = client.post(
        "/api/v1/operator/presence",
        json={"status": "LUNCH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert asyncio.run(_presence_of(ids["busy"])) == "LUNCH"
    # The free (still ACTIVE) operator picked both chats up.
    assignee0, priority0 = asyncio.run(_ticket_state(ids["ticket0"]))
    assignee1, priority1 = asyncio.run(_ticket_state(ids["ticket1"]))
    assert assignee0 == assignee1
    assert assignee0 is not None and assignee0.startswith("free")
    # NORMAL chats became HIGH on release.
    assert priority0 == "HIGH" and priority1 == "HIGH"


def test_offline_release_waits_for_a_freed_slot(client: TestClient) -> None:
    ids, logins = asyncio.run(_seed_scenario())
    # Make the "free" operator full (max 1, one open chat).
    factory = _engine()

    async def _fill() -> None:
        async with factory() as session:
            free = await session.get(Operator, ids["free"])
            assert free is not None
            free.max_active_tickets = 1
            # Everyone else (incl. busy) is capped out of routing.
            await session.execute(
                update(Operator)
                .where(Operator.id != ids["free"])
                .values(max_active_tickets=0)
            )
            channel = Channel(
                channel_type="tag",
                external_channel_id=f"chan-{uuid.uuid4().hex[:8]}",
                display_name="seed",
            )
            session.add(channel)
            user = User(display_name="U2")
            session.add(user)
            await session.flush()
            conversation = Conversation(user_id=user.id, channel_id=channel.id)
            session.add(conversation)
            await session.flush()
            session.add(
                Ticket(
                    conversation_id=conversation.id,
                    user_id=user.id,
                    assignee_id=free.id,
                )
            )
            await session.commit()

    asyncio.run(_fill())

    session = client.post(
        "/api/v1/operator/auth/session",
        auth=(logins["busy"], TOKEN),
    )
    token = session.json()["session_token"]
    released = client.post(
        "/api/v1/operator/presence",
        json={"status": "OFFLINE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert released.status_code == 200

    assignee0, _ = asyncio.run(_ticket_state(ids["ticket0"]))
    assert assignee0 is None  # nobody free: waits in the queue (HIGH)

    # The free operator resolves their own chat -> a slot frees and the
    # released HIGH-priority chats are routed first.
    free_session = client.post(
        "/api/v1/operator/auth/session",
        auth=(logins["free"], TOKEN),
    )
    free_token = free_session.json()["session_token"]
    free_state = client.get(
        "/api/v1/operator/tickets",
        params={"assignee": "me"},
        headers={"Authorization": f"Bearer {free_token}"},
    )
    mine = [t for t in free_state.json()["tickets"] if t["assignee_id"]]
    assert mine, "free operator must have their own chat to resolve"
    resolved = client.post(
        f"/api/v1/operator/tickets/{mine[0]['ticket_id']}/resolve",
        headers={"Authorization": f"Bearer {free_token}"},
    )
    assert resolved.status_code == 200

    assignee0, priority0 = asyncio.run(_ticket_state(ids["ticket0"]))
    assert assignee0 is not None and assignee0.startswith("free")
    assert priority0 == "HIGH"


def _email_of(operator_id: uuid.UUID) -> str:
    factory = _engine()

    async def _get() -> str:
        async with factory() as session:
            operator = await session.get(Operator, operator_id)
            assert operator is not None
            return operator.email

    try:
        return asyncio.run(_get())
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]
