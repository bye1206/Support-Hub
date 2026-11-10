"""Unit tests of the RAG Assistant Gateway client (real contract, D-043).

httpx.MockTransport stands in for the network; no real HTTP. Covered:
headers (X-API-Key + X-User-Id on every request), chat creation, message
roundtrip, and the full error mapping (401/403/404/422/503/timeout).
"""

import json

import httpx
import pytest

from app.integrations.ai.gateway_client import (
    AssistantGatewayClient,
    GatewayAuthError,
    GatewayNotFound,
    GatewayRejected,
    GatewayUnavailable,
)

BASE = "https://gateway.test"


def client_with(handler) -> AssistantGatewayClient:
    return AssistantGatewayClient(
        base_url=BASE, api_key="key-123", transport=httpx.MockTransport(handler)
    )


@pytest.mark.anyio
async def test_create_chat_returns_id(anyio_backend: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": 42, "title": "t"})

    gateway = client_with(handler)
    chat_id = await gateway.create_chat(title="Support dialog", x_user_id="u-1")
    assert chat_id == 42
    assert seen[0].url.path == "/api/v1/chat"
    assert seen[0].headers["x-api-key"] == "key-123"
    assert seen[0].headers["x-user-id"] == "u-1"
    assert json.loads(seen[0].content)["title"] == "Support dialog"


@pytest.mark.anyio
async def test_send_message_returns_answer_and_headers(anyio_backend: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": 0, "answer": "**Готово**"})

    gateway = client_with(handler)
    answer = await gateway.send_message(chat_id=7, query="Помогите", x_user_id="u-2")
    assert answer.answer == "**Готово**"
    assert seen[0].url.path == "/api/v1/message/7"
    assert seen[0].headers["x-api-key"] == "key-123"
    assert seen[0].headers["x-user-id"] == "u-2"
    assert json.loads(seen[0].content) == {"query": "Помогите"}


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.anyio
async def test_auth_errors_map_to_gateway_auth_error(
    anyio_backend: str, status: int
) -> None:
    gateway = client_with(lambda request: httpx.Response(status))
    with pytest.raises(GatewayAuthError):
        await gateway.create_chat(title="t", x_user_id="u")


@pytest.mark.anyio
async def test_404_maps_to_not_found(anyio_backend: str) -> None:
    gateway = client_with(lambda request: httpx.Response(404))
    with pytest.raises(GatewayNotFound):
        await gateway.send_message(chat_id=1, query="q", x_user_id="u")


@pytest.mark.anyio
async def test_422_maps_to_rejected(anyio_backend: str) -> None:
    gateway = client_with(lambda request: httpx.Response(422))
    with pytest.raises(GatewayRejected):
        await gateway.send_message(chat_id=1, query="q", x_user_id="u")


@pytest.mark.anyio
async def test_503_maps_to_unavailable(anyio_backend: str) -> None:
    gateway = client_with(lambda request: httpx.Response(503))
    with pytest.raises(GatewayUnavailable):
        await gateway.send_message(chat_id=1, query="q", x_user_id="u")


@pytest.mark.anyio
async def test_timeout_maps_to_unavailable(anyio_backend: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    gateway = client_with(handler)
    with pytest.raises(GatewayUnavailable):
        await gateway.send_message(chat_id=1, query="q", x_user_id="u")
