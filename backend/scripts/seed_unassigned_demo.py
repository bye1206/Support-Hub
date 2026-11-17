#!/usr/bin/env python3
"""Demo: unassigned chats as they look in the admin "Распределение" block.

Creates 12 chats: a user message arrives through the real Tag ingress, then
SQL moves each ticket into a plain unassigned OPEN state (AI chats are hidden
in the distribution block by design). Used to try the "Показать больше"
window with a full list.
"""

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
BOT_TOKEN = "CHANGE_ME_LOCAL_ONLY_BOT_TOKEN"


def call(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
) -> dict:
    request = urllib.request.Request(f"{BASE}{path}", method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
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
    chats = [
        ("m.petrova", "Добрый день! Не открывается портал с приказами, "
         "крутится загрузка."),
        ("a.sidorov", "Не приходит ссылка для сброса пароля, ящик проверял."),
        ("i.nikitin", "Tag висит при отправке файла больше 20 МБ."),
        ("e.volkova", "Ошибка доступа к общей папке отдела после переезда."),
        ("d.orlov", "Не синхронизируется календарь с телефоном."),
        ("s.morozov", "Пропал доступ к базе заявок с вечера пятницы."),
        ("n.fedorova", "Принтер на 3 этаже выдаёт ошибку картриджа."),
        ("p.kozlov", "Не работает видеосвязь в корпоративном мессенджере."),
        ("o.belova", "Не формируется отчёт за октябрь, кнопка не реагирует."),
        ("v.gusev", "Медленно открываются вкладки портала после обновления."),
        ("k.zaytseva", "Нет уведомлений о новых заявках с утра."),
        ("r.ivanov", "Не прикрепляются файлы к обращению в портале."),
    ]
    ticket_ids: list[str] = []
    conversation_ids: list[str] = []
    for index, (user_name, text) in enumerate(chats):
        incoming = call(
            "POST",
            "/integrations/tag/messages",
            token=BOT_TOKEN,
            body={
                "team_id": "team-1",
                "team_domain": "corp",
                "channel_id": f"chan-demo-unassigned-{index}",
                "channel_name": "support-dm",
                "timestamp": f"2026-11-12T14:{30 + index:02d}:00+03:00",
                "user_id": f"tag-demo-unassigned-{index}",
                "user_name": user_name,
                "post_id": f"post-demo-unassigned-{index}",
                "text": text,
                "file_ids": [],
            },
        )
        conversation_ids.append(incoming["conversation_id"])
        ticket_ids.append(incoming["ticket_id"])
        print("ticket:", incoming["ticket_id"], f"({user_name})")

    import time

    time.sleep(5)  # let the worker drain the AI runs before the SQL pass
    statements: list[str] = [
        f"DELETE FROM outbox_events WHERE payload::text LIKE '%{ticket_id}%'"
        for ticket_id in ticket_ids
    ]
    for index, conversation_id in enumerate(conversation_ids):
        statements.extend(
            [
                "UPDATE conversations SET mode='HUMAN_PENDING',"
                " last_message_sequence = GREATEST(last_message_sequence,"
                " (SELECT COALESCE(MAX(sequence_no), 0) FROM messages"
                f" WHERE conversation_id='{conversation_id}'))"
                f" WHERE id='{conversation_id}'",
                "UPDATE tickets SET status='OPEN', priority='NORMAL',"
                f" assignee_id=NULL, pending_assignee_id=NULL WHERE id='{ticket_ids[index]}'",
            ]
        )
        user_message = (
            "Пробовала и другой браузер — тоже самое. Вчера всё работало."
            if index % 2 == 0
            else "Скажите, когда сможете посмотреть? Проблема не уходит."
        )
        statements.append(
            "INSERT INTO messages (id, conversation_id, sequence_no,"
            " author_type, delivery_state, text, author_user_id,"
            " created_at, updated_at)"
            f" VALUES (gen_random_uuid(), '{conversation_id}',"
            " (SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM messages"
            f" WHERE conversation_id='{conversation_id}'),"
            " 'USER', 'DELIVERED',"
            f" '{user_message}',"
            f" (SELECT user_id FROM conversations WHERE id='{conversation_id}'),"
            " now(), now())"
        )
    sql(statements)
    print(f"{len(ticket_ids)} unassigned demo chats are ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
