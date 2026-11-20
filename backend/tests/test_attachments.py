"""Attachment flows (owner request 2026-11-19).

Covered: composer upload -> reply link -> download; attachment-only
replies; attachment-only inbound messages (webhook, base64); file shows
up in the ticket card; auth on download.
"""

import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.integrations.tag.schemas import TagMessageIn  # noqa: F401 (schema contract)
from app.main import create_app
from tests.conftest import TEST_DB_URL
from tests.fakes import FakeProbe
from tests.test_ai_runs import _seed_user_message
from tests.test_operator_api import TOKEN, _first_ticket_id, headers


@pytest.fixture
def operator_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPERATOR_DEV_TOKEN", TOKEN)
    # Keep the uploaded bytes inside the repo checkout under test.
    monkeypatch.setenv("FILES_DIR", "./data/test-files")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def api_deps():
    db = DatabaseClient(TEST_DB_URL)
    deps = Dependencies(db=db, redis=FakeProbe())  # type: ignore[arg-type]
    yield deps
    import asyncio

    asyncio.run(db.close())


@pytest.fixture
def client(operator_env, api_deps) -> TestClient:
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


@pytest.fixture
def seed(session_factory):
    """Seed a user message through the real ingress flow."""

    async def _seed(text: str = "Не работает VPN") -> tuple[uuid.UUID, uuid.UUID]:
        return await _seed_user_message(session_factory, text=text)

    return _seed



@pytest.mark.anyio
async def test_upload_reply_and_download_roundtrip(client: TestClient, seed) -> None:
    _, _ = await seed()
    ticket_id = _first_ticket_id(client)

    uploaded = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/attachments",
        files={"file": ("report.txt", b"hello attachment", "text/plain")},
        headers=headers(),
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    assert attachment["file_name"] == "report.txt"
    assert attachment["size_bytes"] == len(b"hello attachment")

    replied = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/replies",
        json={
            "text": "Смотрите вложение",
            "attachment_ids": [attachment["id"]],
        },
        headers=headers(),
    )
    assert replied.status_code == 200

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.status_code == 200
    messages = card.json()["messages"]
    last = messages[-1]
    assert last["author_type"] == "OPERATOR"
    assert last["attachments"] == [
        {
            "id": attachment["id"],
            "file_name": "report.txt",
            "mime_type": "text/plain",
            "size_bytes": len(b"hello attachment"),
        }
    ]

    downloaded = client.get(
        f"/api/v1/operator/attachments/{attachment['id']}/file",
        headers=headers(),
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello attachment"



@pytest.mark.anyio
async def test_attachment_only_reply(client: TestClient, seed) -> None:
    _, _ = await seed()
    ticket_id = _first_ticket_id(client)

    uploaded = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/attachments",
        files={"file": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers(),
    )
    assert uploaded.status_code == 200
    attachment_id = uploaded.json()["id"]

    replied = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/replies",
        json={"text": "", "attachment_ids": [attachment_id]},
        headers=headers(),
    )
    assert replied.status_code == 200

    empty = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/replies",
        json={"text": "  "},
        headers=headers(),
    )
    assert empty.status_code == 422



@pytest.mark.anyio
async def test_inbound_message_with_base64_file(client: TestClient) -> None:
    payload = {
        "team_id": "t1",
        "channel_id": "ch-att-1",
        "user_id": "u-att-1",
        "user_name": "Attachment User",
        "post_id": f"post-{uuid.uuid4()}",
        "text": "",
        "files": [
            {
                "file_name": "photo.png",
                "mime_type": "image/png",
                "content_b64": base64.b64encode(b"PNGDATA").decode(),
            }
        ],
    }
    sent = client.post(
        "/api/v1/integrations/tag/messages",
        json=payload,
        headers={"Authorization": "Bearer CHANGE_ME_LOCAL_ONLY_BOT_TOKEN"},
    )
    assert sent.status_code == 200
    ticket_id = sent.json()["ticket_id"]

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.status_code == 200
    user_messages = [
        m for m in card.json()["messages"] if m["author_type"] == "USER"
    ]
    assert user_messages[-1]["attachments"][0]["file_name"] == "photo.png"



@pytest.mark.anyio
async def test_attachment_download_requires_operator(client: TestClient) -> None:
    denied = client.get(f"/api/v1/operator/attachments/{uuid.uuid4()}/file")
    assert denied.status_code == 401
