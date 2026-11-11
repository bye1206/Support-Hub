"""D-031 auto-assignment + P-28 channel auto-tagging on the ingress path."""

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
    Tag,
    Ticket,
    TicketTag,
    User,
)
from tests.conftest import TEST_DB_URL
from tests.fakes import FakeProbe

TOKEN = "test-bot-token-123"


@pytest.fixture
def auto_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BOT_TO_SUPPORT_HUB_TOKEN", TOKEN)
    monkeypatch.setenv("AUTO_ASSIGN_ENABLED", "true")
    monkeypatch.setenv("AUTO_TAG_FROM_CHANNEL", "true")
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
def client(auto_env, api_deps) -> Iterator[TestClient]:
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def payload(post_id: str = "post-auto-1") -> dict:
    return dict(
        team_id="team-1",
        team_domain="corp",
        channel_id="chan-auto",
        channel_name="support-dm",
        timestamp="2026-11-11T12:00:00+03:00",
        user_id="tag-user-auto",
        user_name="Anna Smirnova",
        post_id=post_id,
        text="Автотест входящего",
        file_ids=[],
    )


def _engine():
    return async_sessionmaker(
        create_async_engine(TEST_DB_URL), expire_on_commit=False
    )


async def _seed_open_ticket_for(operator_id: uuid.UUID) -> None:
    """Give the operator one open assigned ticket (skews the least-load pick)."""
    factory = _engine()
    try:
        async with factory() as session:
            channel = Channel(
                channel_type="tag",
                external_channel_id=f"seed-chan-{uuid.uuid4().hex[:8]}",
                display_name="seed",
            )
            session.add(channel)
            await session.flush()
            user = User(display_name="S")
            session.add(user)
            await session.flush()
            conversation = Conversation(user_id=user.id, channel_id=channel.id)
            session.add(conversation)
            await session.flush()
            session.add(
                Ticket(
                    conversation_id=conversation.id,
                    user_id=user.id,
                    assignee_id=operator_id,
                )
            )
            await session.flush()
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
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _add_operator(email: str, max_active: int = 5) -> uuid.UUID:
    factory = _engine()
    try:
        async with factory() as session:
            operator = Operator(
                email=email,
                display_name=email,
                is_active=True,
                max_active_tickets=max_active,
            )
            session.add(operator)
            await session.commit()
            return operator.id
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


async def _ticket_state(ticket_id: uuid.UUID) -> tuple[uuid.UUID | None, list[str]]:
    factory = _engine()
    try:
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            tags = list(
                (
                    await session.scalars(
                        select(Tag.name)
                        .join(TicketTag, TicketTag.tag_id == Tag.id)
                        .where(TicketTag.ticket_id == ticket_id)
                    )
                ).all()
            )
            return ticket.assignee_id, tags
    finally:
        factory.kw["bind"].engine.dispose()  # type: ignore[attr-defined]


def test_least_loaded_operator_gets_new_ticket_and_channel_tag(
    client: TestClient,
) -> None:
    busy = asyncio.run(_add_operator("busy@corp.test"))
    asyncio.run(_add_operator("free@corp.test"))
    asyncio.run(_seed_open_ticket_for(busy))

    body = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers()
    ).json()
    assert body["conversation_created"] is True

    assignee, tags = asyncio.run(_ticket_state(uuid.UUID(body["ticket_id"])))
    assert assignee is not None and assignee != busy  # the free one won
    assert "support-dm" in tags


def test_no_operators_leaves_ticket_unassigned(client: TestClient) -> None:
    body = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers()
    ).json()
    assignee, tags = asyncio.run(_ticket_state(uuid.UUID(body["ticket_id"])))
    assert assignee is None
    assert "support-dm" in tags


def test_auto_assign_skips_operators_at_limit(client: TestClient) -> None:
    """Both operators are at their max_active_tickets: the ticket stays unassigned."""
    busy_a = asyncio.run(_add_operator("lim-a@corp.test", max_active=1))
    busy_b = asyncio.run(_add_operator("lim-b@corp.test", max_active=1))
    asyncio.run(_seed_open_ticket_for(busy_a))
    asyncio.run(_seed_open_ticket_for(busy_b))

    body = client.post(
        "/api/v1/integrations/tag/messages",
        json=payload(post_id="post-auto-2"),
        headers=headers(),
    ).json()
    assignee, _ = asyncio.run(_ticket_state(uuid.UUID(body["ticket_id"])))
    assert assignee is None
