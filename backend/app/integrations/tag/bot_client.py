"""Outbound delivery adapter for the existing Mattermost bot (D-028).

The bot API contract is PROPOSED (implementation plan, 04 §4):
    POST {bot_internal_base_url}/internal/v1/tag/messages
    {"message_id", "conversation_id", "text"}
Support Hub does NOT send to Tag directly — the bot owns that (D-028). The
bot must dedup by message_id: the network is at-least-once (AGENTS.md §6).

Results: 2xx = SENT; everything else raises TagDeliveryError — the outbox
marks the attempt failed and retries with backoff (including timeouts, i.e.
UNKNOWN outcomes are retried until reconciliation says otherwise, R-04).
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BOT_MESSAGES_PATH = "/internal/v1/tag/messages"
DEFAULT_TIMEOUT_SECONDS = 5.0


class TagDeliveryError(Exception):
    """Base: the bot rejected or could not accept the message."""


class TagDeliveryUnknown(TagDeliveryError):
    """Network-level uncertainty (timeout/connect). Outcome UNKNOWN, retriable."""


class TagDeliveryRejected(TagDeliveryError):
    """The bot answered, but not 2xx. Retriable until it stops; 4xx details logged."""


class TagBotClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        service_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` is a test seam (httpx.MockTransport); None = real network."""
        headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers=headers,
            transport=transport,
        )

    async def send_message(self, payload: dict[str, Any]) -> None:
        """Send one outbound message; raises TagDeliveryError subclass on failure."""
        try:
            response = await self._client.post(BOT_MESSAGES_PATH, json=payload)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TagDeliveryUnknown(f"Bot unreachable: {type(exc).__name__}") from exc
        if response.status_code // 100 != 2:
            # No response bodies: never log user text or secrets.
            raise TagDeliveryRejected(
                f"Bot answered HTTP {response.status_code}"
            )

    async def aclose(self) -> None:
        await self._client.aclose()
