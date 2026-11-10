"""Unit tests of the Tag bot delivery adapter and the outbox dispatcher.

The bot API contract is PROPOSED: POST {base}/internal/v1/tag/messages.
httpx MockTransport stands in for the network; no real HTTP.
"""

import httpx
import pytest

from app.integrations.tag.bot_client import (
    TagBotClient,
    TagDeliveryRejected,
    TagDeliveryUnknown,
)
from app.integrations.tag.dispatch import RoutingOutboxHandler
from app.models import OutboxEvent
from app.services.outbox import LoggingOutboxHandler


def client_with(handler) -> TagBotClient:
    return TagBotClient(
        base_url="http://bot.test", transport=httpx.MockTransport(handler)
    )


def event(event_type: str = "message.outbound") -> OutboxEvent:
    return OutboxEvent(
        event_type=event_type,
        aggregate_type="message",
        idempotency_key=f"message:{event_type}-1",
        payload={"message_id": "abc", "conversation_id": "conv-1", "text": "hi"},
    )


class RecordingBot:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(self, payload: dict) -> None:
        self.calls.append(payload)


@pytest.mark.anyio
async def test_send_message_ok(anyio_backend: str) -> None:
    bot = client_with(lambda request: httpx.Response(200))
    await bot.send_message({"message_id": "abc"})


@pytest.mark.anyio
async def test_send_message_5xx_rejected(anyio_backend: str) -> None:
    bot = client_with(lambda request: httpx.Response(500))
    with pytest.raises(TagDeliveryRejected):
        await bot.send_message({"message_id": "abc"})


@pytest.mark.anyio
async def test_send_message_timeout_is_unknown(anyio_backend: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    bot = client_with(handler)
    with pytest.raises(TagDeliveryUnknown):
        await bot.send_message({"message_id": "abc"})


@pytest.mark.anyio
async def test_outbound_payload_hits_bot_path(anyio_backend: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    bot = client_with(handler)
    payload = {"message_id": "m-1", "conversation_id": "c-1", "text": "Привет"}
    await bot.send_message(payload)
    assert seen[0].url.path == "/internal/v1/tag/messages"
    import json

    assert json.loads(seen[0].content.decode()) == payload


@pytest.mark.anyio
async def test_service_token_header_is_sent(anyio_backend: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    bot = TagBotClient(
        base_url="http://bot.test", service_token="secret-token", transport=transport
    )
    await bot.send_message({"message_id": "m-2"})
    assert seen[0].headers["authorization"] == "Bearer secret-token"


@pytest.mark.anyio
async def test_dispatcher_routes_outbound_to_bot(anyio_backend: str) -> None:
    bot = RecordingBot()
    fallback = LoggingOutboxHandler()
    handler = RoutingOutboxHandler(bot=bot, fallback=fallback)
    await handler(event("message.outbound"))
    assert bot.calls == [{"message_id": "abc", "conversation_id": "conv-1", "text": "hi"}]


@pytest.mark.anyio
async def test_dispatcher_falls_back_for_internal_events(anyio_backend: str) -> None:
    bot = RecordingBot()

    class RecordingFallback:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __call__(self, event: OutboxEvent) -> None:
            self.calls.append(event.event_type)

    fallback = RecordingFallback()
    handler = RoutingOutboxHandler(bot=bot, fallback=fallback)
    await handler(event("message.user_received"))
    assert bot.calls == []
    assert fallback.calls == ["message.user_received"]
