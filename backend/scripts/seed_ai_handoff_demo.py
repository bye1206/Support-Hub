#!/usr/bin/env python3
"""Demo: ticket that went through AI and then moved to an operator.

1) A user message arrives through the real Tag ingress (new conversation +
   ticket + NEW status).
2) The dialog is put into HUMAN_PENDING with an open AI handoff and an AI
   reply message (as if the gateway had answered and asked for help).
3) The operator session accepts the handoff via the real API - that writes
   the genuine "handoff.accepted" audit event, which the movement history
   renders as "Принято у ИИ".
4) The ticket is assigned to the same operator via the real API.
"""

import base64
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
BOT_TOKEN = "CHANGE_ME_LOCAL_ONLY_BOT_TOKEN"
DEV_LOGIN = "demo.operator"
PASSWORD_FILE = "/tmp/sh_dev_token"


def call(
    method: str,
    path: str,
    *,
    token: str | None = None,
    basic: str | None = None,
    body: dict | None = None,
) -> dict:
    request = urllib.request.Request(f"{BASE}{path}", method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if basic:
        request.add_header(
            "Authorization", "Basic " + base64.b64encode(basic.encode()).decode()
        )
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, data=data, timeout=30) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def sql(statements: list[str]) -> None:
    import asyncio

    import asyncpg  # type: ignore[import-untyped]

    dsn = open("/tmp/sh_db_dsn").read().strip().replace("+asyncpg", "", 1)

    async def run() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            for statement in statements:
                await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(run())


def main() -> int:
    dev_token = open(PASSWORD_FILE).read().strip()
    incoming = call(
        "POST",
        "/integrations/tag/messages",
        token=BOT_TOKEN,
        body={
            "team_id": "team-1",
            "team_domain": "corp",
            "channel_id": "chan-demo-ai",
            "channel_name": "support-dm",
            "timestamp": "2026-11-12T12:00:00+03:00",
            "user_id": "tag-demo-ai",
            "user_name": "d.orlov",
            "post_id": "post-demo-ai-1",
            "text": "Здравствуйте! Не приходят уведомления в Tag с утра.",
            "file_ids": [],
        },
    )
    conversation_id = incoming["conversation_id"]
    ticket_id = incoming["ticket_id"]
    print("ticket:", ticket_id)

    sql(
        [
            f"UPDATE conversations SET mode='HUMAN_PENDING',"
            f" last_message_sequence = GREATEST(last_message_sequence, 2)"
            f" WHERE id='{conversation_id}'",
            f"UPDATE tickets SET status='AI_PROCESSING' WHERE id='{ticket_id}'",
            "INSERT INTO ai_handoffs (id, conversation_id, reason, is_accepted,"
            " created_at, updated_at)"
            f" VALUES (gen_random_uuid(), '{conversation_id}', 'AI_REQUESTED',"
            " false, now(), now())",
            "INSERT INTO messages (id, conversation_id, sequence_no,"
            " author_type, delivery_state, text, created_at, updated_at)"
            f" VALUES (gen_random_uuid(), '{conversation_id}', 2, 'AI',"
            " 'DELIVERED',"
            " 'Я передал ваш вопрос специалисту поддержки — он ответит"
            " в этом чате.', now(), now())",
        ]
    )

    session = call(
        "POST",
        "/operator/auth/session",
        basic=f"{DEV_LOGIN}:{dev_token}",
    )
    token = session["session_token"]
    accepted = call(
        "POST",
        f"/operator/conversations/{conversation_id}/handoff/accept",
        token=token,
    )
    print("handoff:", accepted)
    assigned = call(
        "POST",
        f"/operator/tickets/{ticket_id}/assign",
        token=token,
        body={"assignee_id": session["operator"]["operator_id"]},
    )
    print("assigned:", assigned)
    replied = call(
        "POST",
        f"/operator/tickets/{ticket_id}/replies",
        token=token,
        body={"text": "Здравствуйте! Уже смотрю проблему с уведомлениями."},
    )
    print("reply:", replied)
    return 0


if __name__ == "__main__":
    sys.exit(main())
