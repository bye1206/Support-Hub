"""RAG Assistant Gateway client — the REAL contract (D-043, owner-provided).

Synchronous HTTP, no callbacks (the old callback design is obsolete):
- POST /api/v1/chat            -> 201 {"id": <int chat_id>, ...}
- POST /api/v1/message/{chat}  -> 201 {"answer": <markdown>, ...}
Headers on every request: X-API-Key (project key), X-User-Id (end-user ref).
The gateway keeps its own context: we send ONLY `query`, never history.
No idempotency on their side: retried POSTs create NEW gateway messages, so
failures are handled at the run level, not blind-retried.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CHAT_PATH = "/api/v1/chat"
MESSAGE_PATH_TEMPLATE = "/api/v1/message/{chat_id}"
# Contract §5: LLM answers take 30-60 s; the hard bound is 120 s.
DEFAULT_TIMEOUT_SECONDS = 130.0


class GatewayError(Exception):
    """Base class for gateway interaction failures."""


class GatewayUnavailable(GatewayError):
    """503 or network-level failure: the LLM backend is unreachable."""


class GatewayAuthError(GatewayError):
    """401/403: API key missing, wrong or lacking permissions."""


class GatewayNotFound(GatewayError):
    """404: the chat does not exist (must be re-created)."""


class GatewayRejected(GatewayError):
    """422/other: our request did not satisfy the contract."""


@dataclass(frozen=True)
class GatewayAnswer:
    answer: str  # markdown text from the gateway (or a trigger code)


class AssistantGatewayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` is a test seam (httpx.MockTransport); None = real network."""
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"X-API-Key": api_key},
            transport=transport,
        )

    async def create_chat(self, *, title: str, x_user_id: str) -> int:
        """Create a gateway chat; returns the chat id (contract §4.1)."""
        data = await self._request(
            "POST",
            CHAT_PATH,
            x_user_id=x_user_id,
            json={"title": title[:255]} if title else {},
            ok_statuses=(200, 201),
        )
        return int(data["id"])

    async def send_message(self, *, chat_id: int, query: str, x_user_id: str) -> GatewayAnswer:
        """Send one user message; waits for the finished answer (§4.2)."""
        data = await self._request(
            "POST",
            MESSAGE_PATH_TEMPLATE.format(chat_id=chat_id),
            x_user_id=x_user_id,
            json={"query": query},
            ok_statuses=(200, 201),
        )
        return GatewayAnswer(answer=str(data["answer"]))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        x_user_id: str,
        json: dict[str, Any],
        ok_statuses: tuple[int, ...],
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, path, json=json, headers={"X-User-Id": x_user_id}
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise GatewayUnavailable(f"Gateway unreachable: {type(exc).__name__}") from exc
        if response.status_code in ok_statuses:
            return response.json()
        if response.status_code in (401, 403):
            raise GatewayAuthError(f"Gateway answered HTTP {response.status_code}")
        if response.status_code == 404:
            raise GatewayNotFound(f"Gateway chat not found: {path}")
        if response.status_code == 503:
            raise GatewayUnavailable("Gateway answered 503 (LLM backend down)")
        # 422 and anything unexpected; no response bodies are logged (user text).
        raise GatewayRejected(f"Gateway answered HTTP {response.status_code}")
