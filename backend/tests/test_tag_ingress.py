"""Integration tests of the Tag ingress webhook on real PostgreSQL (stage 5).

Token plumbing: get_settings() is lru_cached process-wide, so the token is
injected via environment with an explicit cache reset in the fixture.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.main import create_app
from app.models import Channel, Conversation, Message, Ticket, TicketStatus
from tests.conftest import TEST_DB_URL
from tests.fakes import FakeProbe

TOKEN = "test-bot-token-123"


@pytest.fixture
def bot_token_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BOT_TO_SUPPORT_HUB_TOKEN", TOKEN)
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
def client(bot_token_env, api_deps) -> Iterator[TestClient]:
    # Context manager keeps ONE portal/event loop for all requests: asyncpg
    # connections are event-loop-bound and die with a per-request loop.
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


def headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def payload(**overrides: object) -> dict:
    base = dict(
        team_id="team-1",
        team_domain="corp",
        channel_id="chan-1",
        channel_name="support-dm",
        timestamp="2026-11-09T12:00:00+03:00",
        user_id="tag-user-9",
        user_name="Anna Smirnova",
        post_id="post-100",
        text="Входящее через API",
        file_ids=["file-1"],
    )
    base.update(overrides)
    return base


def test_missing_token_is_unauthorized(client: TestClient) -> None:
    response = client.post("/api/v1/integrations/tag/messages", json=payload())
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAUTHORIZED"
    assert "correlation_id" in body


def test_wrong_token_is_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers("nope")
    )
    assert response.status_code == 401


def test_happy_path_creates_full_chain(client: TestClient) -> None:
    response = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sequence_no"] == 1
    assert body["deduplicated"] is False
    assert body["conversation_created"] is True
    assert body["ticket_reopened"] is False

    async def check() -> None:
        engine = create_async_engine(TEST_DB_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                messages = list((await session.scalars(select(Message))).all())
                tickets = list((await session.scalars(select(Ticket))).all())
                channels = list((await session.scalars(select(Channel))).all())
                conversations = list(
                    (await session.scalars(select(Conversation))).all()
                )
                assert len(messages) == 1
                assert len(tickets) == 1
                assert len(conversations) == 1
                assert tickets[0].status == TicketStatus.AI_PROCESSING  # D-039
                assert messages[0].source_created_at is not None
                assert channels[0].channel_type == "tag"
                assert channels[0].external_channel_id == "chan-1"
        finally:
            await engine.dispose()


def test_duplicate_post_id_is_deduplicated(client: TestClient) -> None:
    first = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers()
    )
    second = client.post(
        "/api/v1/integrations/tag/messages", json=payload(), headers=headers()
    )
    assert first.status_code == second.status_code == 200
    assert second.json()["message_id"] == first.json()["message_id"]
    assert second.json()["deduplicated"] is True


def test_invalid_timestamp_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/integrations/tag/messages",
        json=payload(timestamp="не-дата"),
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_epoch_ms_timestamp_is_normalized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/integrations/tag/messages",
        json=payload(timestamp="1762631600000", post_id="post-epoch"),
        headers=headers(),
    )
    assert response.status_code == 200
    assert response.json()["message_id"]


def test_empty_text_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/integrations/tag/messages", json=payload(text=""), headers=headers()
    )
    assert response.status_code == 422
