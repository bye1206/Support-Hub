"""Direct Mattermost/Tag integration (owner request 2026-11-13).

When `TAG_DIRECT_MODE=true`, Support Hub talks to the Mattermost API itself
instead of relying on the external bot:

- inbound: a WebSocket listener on `/api/v4/websocket` receives `posted`
  events for the bot's DM channels and feeds the same ingress pipeline as
  the webhook (dedup by post_id is already in MessageService);
- outbound: replies are delivered via `POST /api/v4/posts` (at-least-once
  outbox semantics unchanged; R-04 reconciliation untouched).

Secrets: the bot token lives in .env (outside git) and is never logged.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.models import Channel, Conversation, Message

logger = logging.getLogger(__name__)

WEBSOCKET_PATH = "/api/v4/websocket"
POSTS_PATH = "/api/v4/posts"
USERS_PATH = "/api/v4/users/{user_id}"
DEFAULT_TIMEOUT_SECONDS = 5.0
# DM channel type in Mattermost (private group would be "G", channel "O").
DM_CHANNEL_TYPE = "D"


class TagDirectError(Exception):
    """Base: Mattermost rejected the request or the payload is unusable."""


class TagDirectUnknown(TagDirectError):
    """Network-level uncertainty (timeout/connect) — retriable."""


class TagDirectRejected(TagDirectError):
    """Mattermost answered, but not 2xx. Retriable until it stops."""


class TagDirectSender:
    """Outbound adapter: delivers one Support Hub reply to Mattermost.

    Implements the `_BotSender` protocol used by RoutingOutboxHandler. The
    outbox payload only carries ids, so the message text and the external
    channel id are resolved from the database here (own short session).
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: Any = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._client = httpx.AsyncClient(
            base_url=settings.mattermost_base_url.rstrip("/"),
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.mattermost_bot_token}"},
            transport=transport,
        )

    async def send_message(self, payload: dict[str, Any]) -> None:
        """Deliver {message_id, conversation_id} as a Mattermost post."""
        channel_id, text = await self._resolve(payload)
        try:
            response = await self._client.post(
                POSTS_PATH,
                json={
                    "channel_id": channel_id,
                    "message": text,
                    "props": {"support_hub_message_id": str(payload["message_id"])},
                },
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TagDirectUnknown(
                f"Mattermost unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code // 100 != 2:
            # Never log user text; status is enough for the outbox retry.
            raise TagDirectRejected(f"Mattermost answered HTTP {response.status_code}")

    async def _resolve(self, payload: dict[str, Any]) -> tuple[str, str]:
        message_id = payload.get("message_id")
        if not message_id:
            raise TagDirectError("Outbox payload without message_id")
        factory = self._session_factory
        if factory is None:
            from sqlalchemy.ext.asyncio import (
                async_sessionmaker,
                create_async_engine,
            )

            engine = create_async_engine(self._settings.database_url, pool_pre_ping=True)
            factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            message = await session.get(Message, message_id)
            if message is None:
                raise TagDirectError(f"Message {message_id} disappeared")
            conversation = await session.get(Conversation, message.conversation_id)
            channel_id = None
            if conversation is not None and conversation.channel_id is not None:
                channel = await session.get(Channel, conversation.channel_id)
                if channel is not None:
                    channel_id = channel.external_channel_id
            if not channel_id:
                raise TagDirectError(
                    f"Conversation {message.conversation_id} has no external channel"
                )
            return channel_id, message.text

    async def aclose(self) -> None:
        await self._client.aclose()


def parse_posted_event(data: dict[str, Any], bot_user_id: str) -> dict[str, Any] | None:
    """Normalize a Mattermost `posted` WebSocket event into ingress fields.

    Returns None for anything that is not a user message in the bot's DM
    (alerts channels, own posts, system posts) so the caller skips it.
    """
    raw_post = data.get("post")
    if not raw_post:
        return None
    try:
        post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
    except (TypeError, json.JSONDecodeError):
        return None
    if data.get("channel_type") != DM_CHANNEL_TYPE:
        return None
    user_id = post.get("user_id")
    if not user_id or user_id == bot_user_id:
        return None  # the bot's own replies must not loop back
    text = (post.get("message") or "").strip()
    if not text:
        return None
    create_at = post.get("create_at")
    source_created_at = None
    if isinstance(create_at, (int, float)) and create_at > 0:
        source_created_at = datetime.fromtimestamp(create_at / 1000, tz=UTC)
    return {
        "channel_id": str(data.get("channel_id") or post.get("channel_id") or ""),
        "user_id": str(user_id),
        "post_id": str(post.get("id") or ""),
        "text": text,
        "source_created_at": source_created_at,
    }


class TagDirectListener:
    """WebSocket listener feeding user DMs into the ingress pipeline.

    Runs as a background asyncio task inside the API process. Reconnects
    with backoff; a broken listener must never take the app down, so all
    errors are caught, logged and retried.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: Any,
        ingest: Any,
        me_user_id: str | None = None,
        ws_factory: Any = None,
    ) -> None:
        """`ingest` is an async callable receiving the normalized fields dict;
        `ws_factory` is a test seam (async callable url+headers -> ws)."""
        self._settings = settings
        self._session_factory = session_factory
        self._ingest = ingest
        self._me_user_id = me_user_id
        self._ws_factory = ws_factory
        self._user_names: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        backoff = 2.0
        base = self._settings.mattermost_base_url.rstrip("/")
        ws_url = f"{base.replace('https://', 'wss://').replace('http://', 'ws://')}{WEBSOCKET_PATH}"
        headers = {"Authorization": f"Bearer {self._settings.mattermost_bot_token}"}
        logger.info("Tag direct listener connecting to %s", ws_url)
        while True:
            try:
                connect: Any = (
                    self._ws_factory(ws_url, headers)
                    if self._ws_factory
                    else _connect_websocket(ws_url, headers)
                )
                async with connect as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "seq": 1,
                                "action": "authentication_challenge",
                                "data": {"token": self._settings.mattermost_bot_token},
                            }
                        )
                    )
                    if self._me_user_id is None:
                        self._me_user_id = await self._fetch_me()
                    backoff = 2.0
                    logger.info("Tag direct listener connected")
                    async for raw in ws:
                        await self._handle_frame(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect, never crash
                logger.warning(
                    "Tag direct listener disconnected: %s; retry in %.0fs",
                    type(exc).__name__,
                    backoff,
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="tag-direct-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _fetch_me(self) -> str:
        base = self._settings.mattermost_base_url.rstrip("/")
        async with httpx.AsyncClient(
            base_url=base,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {self._settings.mattermost_bot_token}"},
        ) as client:
            response = await client.get("/api/v4/users/me")
            response.raise_for_status()
            return str(response.json()["id"])

    async def _handle_frame(self, raw: str | bytes) -> None:
        try:
            frame = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        if frame.get("event") != "posted":
            return
        fields = parse_posted_event(frame.get("data") or {}, self._me_user_id or "")
        if fields is None:
            return
        fields["user_name"] = await self._user_name(fields["user_id"])
        try:
            await self._ingest(fields)
        except Exception:  # noqa: BLE001 - one message must not kill the listener
            logger.exception("Tag direct ingest failed for post %s", fields["post_id"])

    async def _user_name(self, user_id: str) -> str:
        if user_id in self._user_names:
            return self._user_names[user_id]
        try:
            base = self._settings.mattermost_base_url.rstrip("/")
            async with httpx.AsyncClient(
                base_url=base,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                headers={
                    "Authorization": f"Bearer {self._settings.mattermost_bot_token}"
                },
            ) as client:
                response = await client.get(USERS_PATH.format(user_id=user_id))
                response.raise_for_status()
                body = response.json()
            first = (body.get("first_name") or "").strip()
            last = (body.get("last_name") or "").strip()
            full = f"{first} {last}".strip()
            name = full or body.get("username") or body.get("email") or user_id
        except Exception:  # noqa: BLE001 - name is cosmetic
            name = user_id
        self._user_names[user_id] = str(name)
        return self._user_names[user_id]


def _connect_websocket(url: str, headers: dict[str, str]) -> Any:
    """Return a websockets connect context manager (not a coroutine)."""
    from websockets.asyncio.client import connect

    return connect(url, additional_headers=headers)


async def ingest_direct_message(session_factory: Any, fields: dict[str, Any]) -> None:
    """Feed one DM post into the same pipeline as the webhook ingress."""
    from app.repositories.channels import ChannelRepository
    from app.services.messages import MessageService

    async with session_factory() as session:
        channel = await ChannelRepository().get_or_create(
            session,
            channel_type="tag",
            external_channel_id=fields["channel_id"],
            display_name=None,
        )
        await MessageService().handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=fields["user_id"],
            external_user_name=fields.get("user_name"),
            text=fields["text"],
            external_post_id=fields["post_id"] or None,
            source_created_at=fields.get("source_created_at"),
            channel_id=channel.id,
        )


async def fetch_bot_user_id(settings: Settings) -> str:
    """Resolve the bot account id via GET /api/v4/users/me."""
    async with httpx.AsyncClient(
        base_url=settings.mattermost_base_url.rstrip("/"),
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {settings.mattermost_bot_token}"},
    ) as client:
        response = await client.get("/api/v4/users/me")
        response.raise_for_status()
        return str((response.json())["id"])


__all__ = [
    "DM_CHANNEL_TYPE",
    "TagDirectError",
    "TagDirectListener",
    "TagDirectRejected",
    "TagDirectSender",
    "TagDirectUnknown",
    "fetch_bot_user_id",
    "ingest_direct_message",
    "parse_posted_event",
]
