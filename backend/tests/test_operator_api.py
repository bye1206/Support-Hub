"""Integration tests of the Operator API + WebSocket (stage 7, pass 1).

Auth is the DEV mode (P-22 PROPOSED): shared bearer token + email header,
auto-provisioned operator profile. Keycloak (Q-09) arrives in pass 2.

Covered: 401 (no/wrong token, missing identity), 403 (deactivated), queue
list + filters, ticket card with full history, reply -> PENDING_USER,
resolve, close, manual assignment, handoff acceptance, WS event delivery.
"""

import asyncio
import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.infra.redis_client import EVENTS_CHANNEL, RedisClient
from app.integrations.tag.dispatch import RoutingOutboxHandler
from app.main import create_app
from app.models import (
    AiHandoff,
    AuditLog,
    Conversation,
    DialogMode,
    Operator,
    OperatorRole,
    OutboxEvent,
    OutboxStatus,
    Ticket,
    TicketCategory,
)
from app.services.outbox import LoggingOutboxHandler, OutboxService
from tests.conftest import TEST_DB_URL
from tests.fakes import FakeProbe
from tests.test_ai_runs import _seed_user_message

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
    # One portal/loop for all requests: asyncpg connections are loop-bound.
    with TestClient(create_app(deps=api_deps)) as test_client:
        yield test_client


@pytest.fixture
def seed(session_factory):
    """Seed a user message through the real ingress flow."""

    async def _seed(text: str = "Не работает VPN") -> tuple[uuid.UUID, uuid.UUID]:
        return await _seed_user_message(session_factory, text=text)

    return _seed


def headers(token: str = TOKEN, email: str = "op1@corp.test") -> dict[str, str]:
    # HTTP headers are latin-1/ascii: non-ascii names go percent-free latin.
    return {
        "Authorization": f"Bearer {token}",
        "X-Operator-Email": email,
        "X-Operator-Name": "Operator One",
    }


def _first_ticket_id(client: TestClient) -> str:
    listed = client.get("/api/v1/operator/tickets", headers=headers())
    assert listed.status_code == 200
    tickets = listed.json()["tickets"]
    assert len(tickets) >= 1
    return tickets[0]["ticket_id"]


def test_missing_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/v1/operator/tickets")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "OPERATOR_UNAUTHORIZED"


@pytest.mark.anyio
async def test_admin_routes_enforce_confirmed_roles(
    client: TestClient, session_factory
) -> None:
    denied = client.get("/api/v1/admin/overview", headers=headers())
    assert denied.status_code == 403

    # The test operator was auto-provisioned as OPERATOR. Promote it directly
    # here to isolate the route authorization contract from the UI workflow.
    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "op1@corp.test")
            )
        ).first()
        assert operator is not None
        operator.role = OperatorRole.SUPERVISOR
        await session.commit()

    overview = client.get("/api/v1/admin/overview", headers=headers())
    assert overview.status_code == 200
    assert "tickets" in overview.json()
    assert client.get("/api/v1/admin/operators", headers=headers()).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=headers()).status_code == 200
    parent = client.post(
        "/api/v1/admin/categories", headers=headers(), json={"name": "Доступы"}
    )
    assert parent.status_code == 201
    child = client.post(
        "/api/v1/admin/categories",
        headers=headers(),
        json={"name": "VPN", "parent_id": parent.json()["category_id"]},
    )
    assert child.status_code == 201
    cycle = client.put(
        f"/api/v1/admin/categories/{parent.json()['category_id']}",
        headers=headers(),
        json={"name": "Доступы", "parent_id": child.json()["category_id"]},
    )
    assert cycle.status_code == 409
    assert client.post(
        f"/api/v1/admin/categories/{child.json()['category_id']}/deactivate",
        headers=headers(),
    ).status_code == 200
    assert all(
        row["category_id"] != child.json()["category_id"]
        for row in client.get("/api/v1/operator/categories", headers=headers()).json()["categories"]
    )


@pytest.mark.anyio
async def test_admin_deactivation_disables_unassigned_operator(
    client: TestClient, session_factory
) -> None:
    assert client.get("/api/v1/operator/me", headers=headers()).status_code == 200
    target = client.get(
        "/api/v1/operator/me", headers=headers(email="op2@corp.test")
    ).json()["operator_id"]

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "op1@corp.test")
            )
        ).first()
        assert operator is not None
        operator.role = OperatorRole.ADMIN
        await session.commit()
        admin_id = str(operator.id)

    response = client.post(
        f"/api/v1/admin/operators/{target}/deactivate",
        headers=headers(),
        json={},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert admin_id != target  # Distinct staff identities were provisioned.
    assert client.get(
        "/api/v1/operator/me", headers=headers(email="op2@corp.test")
    ).status_code == 403


@pytest.mark.anyio
async def test_deactivation_requires_and_records_ticket_reassignment(
    client: TestClient, session_factory, seed
) -> None:
    await seed()
    ticket_id = uuid.UUID(_first_ticket_id(client))
    admin_id = uuid.UUID(
        client.get("/api/v1/operator/me", headers=headers()).json()["operator_id"]
    )
    target_id = uuid.UUID(
        client.get(
            "/api/v1/operator/me", headers=headers(email="op2@corp.test")
        ).json()["operator_id"]
    )
    replacement_id = uuid.UUID(
        client.get(
            "/api/v1/operator/me", headers=headers(email="op3@corp.test")
        ).json()["operator_id"]
    )

    async with session_factory() as session:
        admin = await session.get(Operator, admin_id)
        ticket = await session.get(Ticket, ticket_id)
        assert admin is not None and ticket is not None
        admin.role = OperatorRole.ADMIN
        ticket.assignee_id = target_id
        await session.commit()

    missing_replacement = client.post(
        f"/api/v1/admin/operators/{target_id}/deactivate", headers=headers(), json={}
    )
    assert missing_replacement.status_code == 409

    result = client.post(
        f"/api/v1/admin/operators/{target_id}/deactivate",
        headers=headers(),
        json={"reassign_to": str(replacement_id)},
    )
    assert result.status_code == 200
    async with session_factory() as session:
        ticket = await session.get(Ticket, ticket_id)
        assert ticket is not None and ticket.assignee_id == replacement_id
        assert await session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "ticket.reassigned",
                AuditLog.entity_id == ticket_id,
            )
        ) is not None


def test_wrong_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/v1/operator/tickets", headers=headers(token="nope"))
    assert response.status_code == 401


def test_missing_email_header_is_unauthorized(client: TestClient) -> None:
    response = client.get(
        "/api/v1/operator/tickets", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "OPERATOR_IDENTITY_MISSING"


@pytest.mark.anyio
async def test_deactivated_operator_is_forbidden(
    client: TestClient, session_factory
) -> None:
    # First request provisions the profile; deactivate it in DB afterwards.
    ok = client.get("/api/v1/operator/tickets", headers=headers())
    assert ok.status_code == 200

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "op1@corp.test")
            )
        ).first()
        assert operator is not None
        operator.is_active = False
        await session.commit()

    blocked = client.get("/api/v1/operator/tickets", headers=headers())
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "OPERATOR_DEACTIVATED"


@pytest.mark.anyio
async def test_queue_lists_tickets_and_filters_by_status(client: TestClient, seed) -> None:
    await seed()
    listed = client.get("/api/v1/operator/tickets", headers=headers())
    assert listed.status_code == 200
    tickets = listed.json()["tickets"]
    assert len(tickets) == 1
    assert tickets[0]["status"] == "AI_PROCESSING"  # D-039 ingress effect

    open_only = client.get(
        "/api/v1/operator/tickets", params={"status": "OPEN"}, headers=headers()
    )
    assert open_only.status_code == 200
    assert open_only.json()["tickets"] == []


@pytest.mark.anyio
async def test_ticket_card_contains_full_history(client: TestClient, seed) -> None:
    _, conversation_id = await seed()
    ticket_id = _first_ticket_id(client)

    replied = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/replies",
        json={"text": "Передаём специалисту"},
        headers=headers(),
    )
    assert replied.status_code == 200
    assert replied.json()["status"] == "PENDING_USER"

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.status_code == 200
    body = card.json()
    assert body["conversation_id"] == str(conversation_id)
    authors = [m["author_type"] for m in body["messages"]]
    assert authors == ["USER", "OPERATOR"]
    assert body["messages"][1]["text"] == "Передаём специалисту"


@pytest.mark.anyio
async def test_resolve_then_close_ticket(client: TestClient, seed) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)

    resolved = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/resolve", headers=headers()
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"

    closed = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/close", headers=headers()
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"


@pytest.mark.anyio
async def test_assign_and_unassign_ticket(client: TestClient, seed, session_factory) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)

    async with session_factory() as session:
        operator = (await session.scalars(select(Operator))).one()
        operator_id = operator.id

    assigned = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignee_id"] == str(operator_id)

    mine = client.get(
        "/api/v1/operator/tickets", params={"assignee": "me"}, headers=headers()
    )
    assert [t["ticket_id"] for t in mine.json()["tickets"]] == [ticket_id]

    unassigned = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/assign",
        json={"assignee_id": None},
        headers=headers(),
    )
    assert unassigned.status_code == 200
    assert unassigned.json()["assignee_id"] is None


@pytest.mark.anyio
async def test_accept_handoff_then_second_attempt_conflicts(
    client: TestClient, seed, session_factory
) -> None:
    """AI operator-trigger puts the dialog into HUMAN_PENDING; the operator
    claims it (D-014). Second accept -> 409."""
    from app.services.ai_runs import AiRunService
    from tests.test_ai_runs import FakeGateway

    message_id, conversation_id = await seed()
    operator_code = get_settings().ai_trigger_operator_code
    service = AiRunService(gateway=FakeGateway(operator_code))
    await service.ensure_run_for_message(session_factory, message_id)
    await service.process_pending(session_factory)

    accepted = client.post(
        f"/api/v1/operator/conversations/{conversation_id}/handoff/accept",
        headers=headers(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["mode"] == "HUMAN_ACTIVE"

    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.mode == DialogMode.HUMAN_ACTIVE
        handoff = (await session.scalars(select(AiHandoff))).one()
        assert handoff.is_accepted is True

    again = client.post(
        f"/api/v1/operator/conversations/{conversation_id}/handoff/accept",
        headers=headers(),
    )
    assert again.status_code == 409


@pytest.mark.anyio
async def test_unknown_ticket_is_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/operator/tickets/{uuid.uuid4()}", headers=headers())
    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_and_list_note(client: TestClient, seed, session_factory) -> None:
    _, conversation_id = await seed()
    _first_ticket_id(client)  # authenticated call auto-provisions the profile

    async with session_factory() as session:
        operator = (await session.scalars(select(Operator))).one()
        operator_id = operator.id

    created = client.post(
        f"/api/v1/operator/conversations/{conversation_id}/notes",
        json={"body": "Проверить у отдела сети"},
        headers=headers(),
    )
    assert created.status_code == 201
    assert created.json()["body"] == "Проверить у отдела сети"
    assert created.json()["author_id"] == str(operator_id)

    listed = client.get(
        f"/api/v1/operator/conversations/{conversation_id}/notes", headers=headers()
    )
    assert listed.status_code == 200
    notes = listed.json()["notes"]
    assert len(notes) == 1
    assert notes[0]["note_id"] == created.json()["note_id"]


@pytest.mark.anyio
async def test_note_is_not_a_message_and_keeps_status(
    client: TestClient, seed, session_factory
) -> None:
    """D-025: a note never reaches the public history and changes no status."""
    _, conversation_id = await seed()
    ticket_id = _first_ticket_id(client)

    created = client.post(
        f"/api/v1/operator/conversations/{conversation_id}/notes",
        json={"body": "Секретная служебная заметка"},
        headers=headers(),
    )
    assert created.status_code == 201

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.status_code == 200
    body = card.json()
    texts = [m["text"] for m in body["messages"]]
    assert "Секретная служебная заметка" not in texts
    assert [m["author_type"] for m in body["messages"]] == ["USER"]
    assert body["status"] == "AI_PROCESSING"  # a note must not move the status


@pytest.mark.anyio
async def test_note_unknown_conversation_is_404(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/operator/conversations/{uuid.uuid4()}/notes",
        json={"body": "Текст"},
        headers=headers(),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_set_category_and_filter_queue(
    client: TestClient, seed, session_factory
) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)

    async with session_factory() as session:
        category = TicketCategory(name="Техническая поддержка")
        session.add(category)
        await session.commit()
        category_id = category.id

    set_category = client.patch(
        f"/api/v1/operator/tickets/{ticket_id}/category",
        json={"category_id": str(category_id)},
        headers=headers(),
    )
    assert set_category.status_code == 200
    assert set_category.json()["category_id"] == str(category_id)

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.json()["category_id"] == str(category_id)

    filtered = client.get(
        "/api/v1/operator/tickets",
        params={"category": str(category_id)},
        headers=headers(),
    )
    assert [t["ticket_id"] for t in filtered.json()["tickets"]] == [ticket_id]

    cleared = client.patch(
        f"/api/v1/operator/tickets/{ticket_id}/category",
        json={"category_id": None},
        headers=headers(),
    )
    assert cleared.status_code == 200
    assert cleared.json()["category_id"] is None


@pytest.mark.anyio
async def test_set_unknown_category_is_404(client: TestClient, seed) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)
    response = client.patch(
        f"/api/v1/operator/tickets/{ticket_id}/category",
        json={"category_id": str(uuid.uuid4())},
        headers=headers(),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_add_tag_is_case_insensitive_and_idempotent(
    client: TestClient, seed
) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)

    first = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/tags",
        json={"name": "VPN"},
        headers=headers(),
    )
    assert first.status_code == 200
    assert first.json()["name"] == "VPN"

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.json()["tags"] == ["VPN"]

    # Same tag with another case: the same row, the link is not duplicated.
    second = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/tags",
        json={"name": "vpn"},
        headers=headers(),
    )
    assert second.status_code == 200
    assert second.json()["tag_id"] == first.json()["tag_id"]

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.json()["tags"] == ["VPN"]


@pytest.mark.anyio
async def test_remove_tag(client: TestClient, seed) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)
    tag_id = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/tags",
        json={"name": "Срочный"},
        headers=headers(),
    ).json()["tag_id"]

    removed = client.delete(
        f"/api/v1/operator/tickets/{ticket_id}/tags/{tag_id}", headers=headers()
    )
    assert removed.status_code == 204

    card = client.get(f"/api/v1/operator/tickets/{ticket_id}", headers=headers())
    assert card.json()["tags"] == []

    # Removing the same tag twice -> 409 (no link left).
    again = client.delete(
        f"/api/v1/operator/tickets/{ticket_id}/tags/{tag_id}", headers=headers()
    )
    assert again.status_code == 409


@pytest.mark.anyio
async def test_queue_filter_by_tag(client: TestClient, seed) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)
    added = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/tags",
        json={"name": "VPN"},
        headers=headers(),
    )
    assert added.status_code == 200

    by_tag = client.get(
        "/api/v1/operator/tickets", params={"tag": "vpn"}, headers=headers()
    )
    assert [t["ticket_id"] for t in by_tag.json()["tickets"]] == [ticket_id]
    assert by_tag.json()["tickets"][0]["tags"] == ["VPN"]

    other = client.get(
        "/api/v1/operator/tickets", params={"tag": "другое"}, headers=headers()
    )
    assert other.json()["tickets"] == []


@pytest.mark.anyio
async def test_operator_reply_reaches_bot_via_outbox(
    client: TestClient, seed, session_factory
) -> None:
    """Stage-7 criterion: reply -> PENDING_USER -> Outbox -> bot (mock)."""
    _, conversation_id = await seed()
    ticket_id = _first_ticket_id(client)

    replied = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/replies",
        json={"text": "Передаём специалисту"},
        headers=headers(),
    )
    assert replied.status_code == 200
    assert replied.json()["status"] == "PENDING_USER"
    reply_message_id = replied.json()["message_id"]

    delivered: list[dict] = []

    class OkBot:
        async def send_message(self, payload: dict) -> None:
            delivered.append(payload)

    handler = RoutingOutboxHandler(bot=OkBot(), fallback=LoggingOutboxHandler())
    async with session_factory() as session:
        # message.user_received (ingress) + message.outbound (the reply).
        dispatched = await OutboxService(handler=handler).process_batch(session)

    assert dispatched == 2
    assert delivered == [
        {
            "message_id": reply_message_id,
            "conversation_id": str(conversation_id),
        }
    ]

    async with session_factory() as check:
        row = (
            await check.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "message.outbound"
                )
            )
        ).one()
        assert row.status == OutboxStatus.PROCESSED


@pytest.mark.anyio
async def test_queue_pagination(client: TestClient, session_factory) -> None:
    for user in ("user-a", "user-b", "user-c"):
        await _seed_user_message(session_factory, external_user_id=user, text=f"Вопрос {user}")

    all_ids = {
        t["ticket_id"] for t in client.get(
            "/api/v1/operator/tickets", headers=headers()
        ).json()["tickets"]
    }
    assert len(all_ids) == 3

    page1 = client.get(
        "/api/v1/operator/tickets", params={"limit": 2, "offset": 0}, headers=headers()
    )
    page2 = client.get(
        "/api/v1/operator/tickets", params={"limit": 2, "offset": 2}, headers=headers()
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    ids1 = [t["ticket_id"] for t in page1.json()["tickets"]]
    ids2 = [t["ticket_id"] for t in page2.json()["tickets"]]
    assert len(ids1) == 2
    assert len(ids2) == 1
    assert not set(ids1) & set(ids2)
    assert set(ids1) | set(ids2) == all_ids


@pytest.mark.anyio
async def test_ticket_card_does_not_leak_other_conversation(
    client: TestClient, session_factory
) -> None:
    """Security (09 §3): each card carries only its own conversation's history."""
    await _seed_user_message(session_factory, external_user_id="user-a", text="Проблема А")
    await _seed_user_message(session_factory, external_user_id="user-b", text="Проблема Б")

    listed = client.get("/api/v1/operator/tickets", headers=headers())
    assert listed.status_code == 200
    tickets = listed.json()["tickets"]
    assert len(tickets) == 2

    by_conversation: dict[str, list[str]] = {}
    for ticket in tickets:
        card = client.get(f"/api/v1/operator/tickets/{ticket['ticket_id']}", headers=headers())
        assert card.status_code == 200
        body = card.json()
        by_conversation[body["conversation_id"]] = [m["text"] for m in body["messages"]]

    assert len(by_conversation) == 2
    assert sorted(by_conversation.values()) == [["Проблема А"], ["Проблема Б"]]


@pytest.mark.anyio
async def test_get_current_operator_profile(client: TestClient) -> None:
    me = client.get("/api/v1/operator/me", headers=headers())
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "op1@corp.test"
    assert body["display_name"] == "Operator One"
    assert body["role"] == "OPERATOR"

    # Stage-8 UI sends only token + email (non-Latin names break HTTP
    # headers): display_name must fall back to the email.
    anon = client.get(
        "/api/v1/operator/me",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Operator-Email": "op2@corp.test",
        },
    )
    assert anon.status_code == 200
    assert anon.json()["display_name"] == "op2@corp.test"


@pytest.mark.anyio
async def test_list_categories(client: TestClient, seed, session_factory) -> None:
    await seed()
    async with session_factory() as session:
        session.add(TicketCategory(name="Техническая поддержка"))
        await session.commit()

    listed = client.get("/api/v1/operator/categories", headers=headers())
    assert listed.status_code == 200
    assert [c["name"] for c in listed.json()["categories"]] == [
        "Техническая поддержка"
    ]


@pytest.mark.anyio
async def test_list_user_previous_tickets(
    client: TestClient, session_factory
) -> None:
    """Customer card (docs/06 §5): only this user's recent tickets."""
    await _seed_user_message(
        session_factory, external_user_id="user-a", text="Первый вопрос"
    )
    await _seed_user_message(
        session_factory, external_user_id="user-b", text="Чужой вопрос"
    )

    listed = client.get("/api/v1/operator/tickets", headers=headers())
    assert listed.status_code == 200
    tickets = listed.json()["tickets"]
    assert len(tickets) == 2

    # Map user_id -> the ticket's own text via each card.
    text_by_user: dict[str, list[str]] = {}
    for ticket in tickets:
        card = client.get(
            f"/api/v1/operator/tickets/{ticket['ticket_id']}", headers=headers()
        )
        text_by_user[ticket["user_id"]] = [
            m["text"] for m in card.json()["messages"]
        ]
    user_a = next(u for u, t in text_by_user.items() if "Первый вопрос" in t)
    user_b = next(u for u, t in text_by_user.items() if "Чужой вопрос" in t)

    history = client.get(
        f"/api/v1/operator/users/{user_a}/tickets", headers=headers()
    )
    assert history.status_code == 200
    rows = history.json()["tickets"]
    assert [t["user_id"] for t in rows] == [user_a]
    assert user_b not in [t["user_id"] for t in rows]


@pytest.mark.anyio
async def test_assignment_history_records_assignee(
    client: TestClient, seed, session_factory
) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)
    async with session_factory() as session:
        operator = (await session.scalars(select(Operator))).one()
        operator_id = operator.id

    assigned = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/assign",
        json={"assignee_id": str(operator_id)},
        headers=headers(),
    )
    assert assigned.status_code == 200

    history = client.get(
        f"/api/v1/operator/tickets/{ticket_id}/assignment-history",
        headers=headers(),
    )
    assert history.status_code == 200
    events = history.json()["events"]
    assert len(events) == 1
    assert events[0]["actor_id"] == str(operator_id)
    assert events[0]["assignee_id"] == str(operator_id)

    missing = client.get(
        f"/api/v1/operator/tickets/{uuid.uuid4()}/assignment-history",
        headers=headers(),
    )
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_tag_details_for_card_actions(client: TestClient, seed) -> None:
    await seed()
    ticket_id = _first_ticket_id(client)
    created = client.post(
        f"/api/v1/operator/tickets/{ticket_id}/tags",
        json={"name": "VPN"},
        headers=headers(),
    )
    assert created.status_code == 200

    details = client.get(
        f"/api/v1/operator/tickets/{ticket_id}/tag-details", headers=headers()
    )
    assert details.status_code == 200
    assert details.json()["tags"] == [
        {"tag_id": created.json()["tag_id"], "name": "VPN"}
    ]

    missing = client.get(
        f"/api/v1/operator/tickets/{uuid.uuid4()}/tag-details", headers=headers()
    )
    assert missing.status_code == 404


def test_ws_delivers_published_events(operator_env) -> None:
    """Real Redis pub/sub delivery, verified against a real uvicorn loop.

    TestClient runs the app on a side-thread portal; on this dev stack
    server-initiated pushes to an idle socket do not wake the portal loop,
    so delivery is proven against a production-shaped uvicorn server.
    The publisher is a SYNC redis client (an asyncio client would be bound
    to the wrong loop); the test waits for the server's `ready` frame
    before publishing - pub/sub retains nothing, an earlier publish
    would be lost."""
    import time

    import redis as sync_redis
    import uvicorn
    from websockets.sync.client import connect as ws_connect

    real_redis = RedisClient("redis://127.0.0.1:6379/0")
    deps = Dependencies(db=FakeProbe(), redis=real_redis)  # type: ignore[arg-type]
    server = uvicorn.Server(
        uvicorn.Config(create_app(deps=deps), host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]  # type: ignore[attr-defined]
    try:
        published = {
            "type": "message.user_received",
            "payload": {"message_id": str(uuid.uuid4())},
        }
        with ws_connect(f"ws://127.0.0.1:{port}/ws?token={TOKEN}") as ws:
            ready = json.loads(ws.recv(timeout=10))
            assert ready["type"] == "ready"
            publisher = sync_redis.Redis.from_url("redis://127.0.0.1:6379/0")
            try:
                publisher.publish(EVENTS_CHANNEL, json.dumps(published))
                received = json.loads(ws.recv(timeout=10))
            finally:
                publisher.close()
            assert received["type"] == "message.user_received"
            assert (
                received["payload"]["message_id"]
                == published["payload"]["message_id"]
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(real_redis.close())


def test_ws_rejects_bad_token(operator_env, api_deps) -> None:
    real_redis = RedisClient("redis://127.0.0.1:6379/0")
    deps = Dependencies(db=api_deps.db, redis=real_redis)  # type: ignore[arg-type]
    with TestClient(create_app(deps=deps)) as client:
        with pytest.raises(Exception):  # noqa: B017 - starlette raises on 1008
            with client.websocket_connect("/ws?token=wrong"):
                pass
    asyncio.run(real_redis.close())
