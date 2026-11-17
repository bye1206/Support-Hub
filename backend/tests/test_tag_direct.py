"""Direct Mattermost integration: event parsing and outbound sender."""

import json
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.integrations.tag.direct import (
    TagDirectError,
    TagDirectSender,
    parse_posted_event,
)


@pytest.fixture
def direct_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TAG_DIRECT_MODE", "false")
    monkeypatch.setenv("MATTERMOST_BASE_URL", "https://tag.example.test")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-token")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def _posted_event(channel_type: str = "D", user_id: str = "user1") -> dict[str, Any]:
    post = {
        "id": "post-1",
        "user_id": user_id,
        "channel_id": "chan-1",
        "message": "Привет, не работает принтер",
        "create_at": 1765492200000,
    }
    return {
        "event": "posted",
        "data": {
            "channel_type": channel_type,
            "channel_id": "chan-1",
            "post": json.dumps(post),
        },
    }


def test_posted_event_user_dm_is_normalized() -> None:
    fields = parse_posted_event(_posted_event()["data"], bot_user_id="bot1")
    assert fields is not None
    assert fields["channel_id"] == "chan-1"
    assert fields["user_id"] == "user1"
    assert fields["post_id"] == "post-1"
    assert fields["text"] == "Привет, не работает принтер"
    assert fields["source_created_at"] is not None


def test_posted_event_bot_own_post_is_skipped() -> None:
    assert parse_posted_event(_posted_event(user_id="bot1")["data"], "bot1") is None


def test_posted_event_group_channel_is_skipped() -> None:
    event = _posted_event(channel_type="G")
    assert parse_posted_event(event["data"], "bot1") is None


def test_posted_event_without_post_is_skipped() -> None:
    assert parse_posted_event({"channel_type": "D"}, "bot1") is None


@pytest.mark.anyio
async def test_sender_posts_to_mattermost(direct_env) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"status": "ok"})

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, model: Any, id: Any):  # noqa: A002
            if model.__name__ == "Message":
                return type(
                    "M",
                    (),
                    {"id": id, "text": "Ответ оператора", "conversation_id": "conv-1"},
                )()
            if model.__name__ == "Conversation":
                return type("C", (), {"id": id, "channel_id": "ch-row"})()
            if model.__name__ == "Channel":
                return type("Ch", (), {"external_channel_id": "chan-1"})()
            return None

    sender = TagDirectSender(
        direct_env, session_factory=lambda: _Session(), transport=httpx.MockTransport(handler)
    )
    await sender.send_message({"message_id": "m1", "conversation_id": "conv-1"})
    await sender.aclose()
    assert captured["url"].endswith("/api/v4/posts")
    assert captured["auth"] == "Bearer mm-token"
    assert captured["body"]["channel_id"] == "chan-1"
    assert captured["body"]["message"] == "Ответ оператора"
    assert captured["body"]["props"]["support_hub_message_id"] == "m1"


@pytest.mark.anyio
async def test_sender_rejects_non_2xx(direct_env) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={})

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, model: Any, id: Any):  # noqa: A002
            if model.__name__ == "Message":
                return type("M", (), {"id": id, "text": "t", "conversation_id": "c"})()
            if model.__name__ == "Conversation":
                return type("C", (), {"id": id, "channel_id": "ch"})()
            return type("Ch", (), {"external_channel_id": "chan"})()

    sender = TagDirectSender(
        direct_env, session_factory=lambda: _Session(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(TagDirectError):
        await sender.send_message({"message_id": "m1", "conversation_id": "c"})
    await sender.aclose()
