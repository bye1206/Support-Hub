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
FILES_PATH = "/api/v4/files"
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
        self._fallback_engine: Any = None  # built once, disposed with the client
        self._client = httpx.AsyncClient(
            base_url=settings.mattermost_base_url.rstrip("/"),
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.mattermost_bot_token}"},
            transport=transport,
        )

    async def send_message(self, payload: dict[str, Any]) -> None:
        """Deliver {message_id, conversation_id} as a Mattermost post.

        Owner request (2026-11-19): if the message carries attachments, the
        files are uploaded first (POST /api/v4/files) and referenced by the
        post's file_ids.
        """
        channel_id, text, attachments = await self._resolve(payload)
        file_ids: list[str] = []
        if attachments:
            from app.infra.file_storage import FileStorageError, LocalFileStorage

            storage = LocalFileStorage()
            for file_name, mime, storage_key in attachments:
                try:
                    content = await storage.open(storage_key)
                except FileStorageError as exc:
                    raise TagDirectError(
                        f"Attachment file missing: {type(exc).__name__}"
                    ) from exc
                try:
                    response = await self._client.post(
                        FILES_PATH,
                        params={"channel_id": channel_id, "filename": file_name},
                        files={
                            "files": (
                                file_name,
                                content,
                                mime or "application/octet-stream",
                            )
                        },
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    raise TagDirectUnknown(
                        f"Mattermost unreachable: {type(exc).__name__}"
                    ) from exc
                if response.status_code // 100 != 2:
                    raise TagDirectRejected(
                        f"Mattermost file upload answered HTTP {response.status_code}"
                    )
                infos = response.json().get("file_infos") or []
                file_ids.extend(str(info["id"]) for info in infos if info.get("id"))
        try:
            body: dict[str, Any] = {
                "channel_id": channel_id,
                "message": text,
                "props": {"support_hub_message_id": str(payload["message_id"])},
            }
            if file_ids:
                body["file_ids"] = file_ids
            # Owner request (2026-11-19): the closure note carries five
            # interactive rating buttons (5..1); Mattermost calls the
            # integration URL with the button context. Owner (2026-11-25):
            # the Tag team's recommended setup routes clicks through THEIR
            # working rating endpoint (public HTTPS, trusted cert — direct
            # calls to our internal IP are blocked by Mattermost), so the
            # button URL is overridable via TAG_RATING_BUTTON_URL; the
            # context format (ticket_id + score) stays ours either way.
            if payload.get("rating_request"):
                from app.config import get_settings

                settings = get_settings()
                rating_url = settings.tag_rating_button_url or (
                    f"{settings.app_base_url.rstrip('/')}/api/v1/integrations/"
                    f"tag/rating?token={settings.bot_webhook_token}"
                )
                ticket_id = str(payload.get("ticket_id", ""))
                body["props"]["attachments"] = [
                    {
                        "text": "Оцените, пожалуйста, работу поддержки:",
                        "actions": [
                            {
                                "id": f"rate_{score}",
                                "name": str(score),
                                "type": "button",
                                "integration": {
                                    "url": rating_url,
                                    "context": {
                                        "ticket_id": ticket_id,
                                        "score": score,
                                    },
                                },
                            }
                            for score in (5, 4, 3, 2, 1)
                        ],
                    }
                ]
            response = await self._client.post(POSTS_PATH, json=body)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TagDirectUnknown(
                f"Mattermost unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code // 100 != 2:
            # Never log user text; status is enough for the outbox retry.
            raise TagDirectRejected(f"Mattermost answered HTTP {response.status_code}")

    async def _resolve(
        self, payload: dict[str, Any]
    ) -> tuple[str, str, list[tuple[str, str, str]]]:
        """Returns (channel_id, text, attachments[(name, mime, storage_key)])."""
        message_id = payload.get("message_id")
        if not message_id:
            raise TagDirectError("Outbox payload without message_id")
        factory = self._session_factory
        if factory is None:
            # Perf (2026-11-17): build the fallback engine ONCE — a new engine
            # per message leaked asyncpg connections under load.
            if self._fallback_engine is None:
                from sqlalchemy.ext.asyncio import (
                    async_sessionmaker,
                    create_async_engine,
                )

                self._fallback_engine = create_async_engine(
                    self._settings.database_url, pool_pre_ping=True
                )
                self._session_factory = async_sessionmaker(
                    self._fallback_engine, expire_on_commit=False
                )
            factory = self._session_factory
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
            from app.repositories.attachments import AttachmentRepository

            attachments = [
                (a.file_name, a.mime_type, a.storage_key)
                for a in await AttachmentRepository().for_message(session, message.id)
            ]
            return channel_id, message.text, attachments

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
    # Owner request (2026-11-19): a post may be attachment-only.
    file_ids = [str(f) for f in (post.get("file_ids") or []) if f]
    if not text and not file_ids:
        return None
    metadata = post.get("metadata") or {}
    files_meta = {
        str(f.get("id")): f
        for f in (metadata.get("files") or [])
        if isinstance(f, dict) and f.get("id")
    }
    create_at = post.get("create_at")
    source_created_at = None
    if isinstance(create_at, (int, float)) and create_at > 0:
        source_created_at = datetime.fromtimestamp(create_at / 1000, tz=UTC)
    return {
        "channel_id": str(data.get("channel_id") or post.get("channel_id") or ""),
        "user_id": str(user_id),
        "post_id": str(post.get("id") or ""),
        "text": text,
        "file_ids": file_ids,
        "files_meta": files_meta,
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
        self._user_names: dict[str, dict[str, str]] = {}
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
        profile = await self._user_profile(fields["user_id"])
        fields["user_name"] = profile["username"] or profile["display"]
        fields["user_display_name"] = profile["display"]
        fields["user_email"] = profile["email"]
        # Owner request (2026-11-19): download the user's files from
        # Mattermost so the workspace can show them.
        fields["files"] = await self._download_files(fields)
        try:
            await self._ingest(fields)
        except Exception:  # noqa: BLE001 - one message must not kill the listener
            logger.exception("Tag direct ingest failed for post %s", fields["post_id"])

    async def _download_files(self, fields: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch one post's files; a failed download skips that file (logged)."""
        out: list[dict[str, Any]] = []
        for file_id in fields.get("file_ids") or []:
            meta = (fields.get("files_meta") or {}).get(file_id, {})
            try:
                async with httpx.AsyncClient(
                    base_url=self._settings.mattermost_base_url.rstrip("/"),
                    timeout=30.0,
                    headers={
                        "Authorization": f"Bearer {self._settings.mattermost_bot_token}"
                    },
                ) as client:
                    response = await client.get(f"{FILES_PATH}/{file_id}")
                    response.raise_for_status()
            except httpx.HTTPError:
                logger.warning(
                    "Tag direct: file %s of post %s could not be downloaded",
                    file_id,
                    fields["post_id"],
                )
                continue
            out.append(
                {
                    "file_name": str(meta.get("name") or file_id),
                    "mime_type": str(meta.get("mime_type") or ""),
                    "content": response.content,
                }
            )
        return out

    async def _user_profile(self, user_id: str) -> dict[str, str]:
        """Tag profile: display name, handle and e-mail (owner diagnostic
        2026-11-20: the handle — not the pretty name — is the AD match key;
        the e-mail is the exact one)."""
        cached = self._user_names.get(user_id)
        if cached is not None:
            return cached
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
            profile = {
                "display": full or body.get("username") or body.get("email") or user_id,
                "username": (body.get("username") or "").strip(),
                "email": (body.get("email") or "").strip(),
            }
        except Exception:  # noqa: BLE001 - profile is cosmetic
            profile = {"display": user_id, "username": "", "email": ""}
        self._user_names[user_id] = profile
        return profile


def _connect_websocket(url: str, headers: dict[str, str]) -> Any:
    """Return a websockets connect context manager (not a coroutine)."""
    from websockets.asyncio.client import connect

    return connect(url, additional_headers=headers)


async def ingest_direct_message(session_factory: Any, fields: dict[str, Any]) -> None:
    """Feed one DM post into the same pipeline as the webhook ingress."""
    from app.repositories.channels import ChannelRepository
    from app.services.messages import IncomingFile, MessageService

    files = [
        IncomingFile(
            file_name=file["file_name"],
            mime_type=file["mime_type"],
            content=file["content"],
        )
        for file in fields.get("files") or []
    ]
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
            display_name=fields.get("user_display_name"),
            email=fields.get("user_email") or None,
            text=fields["text"],
            external_post_id=fields["post_id"] or None,
            source_created_at=fields.get("source_created_at"),
            channel_id=channel.id,
            files=files,
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


async def fetch_tag_avatar(settings: Settings, external_user_id: str) -> bytes | None:
    """Mattermost profile image for a Tag user (owner report, 2026-11-20:
    the avatar fallback when AD keeps no photo for the account)."""
    if not settings.mattermost_bot_token:
        return None
    async with httpx.AsyncClient(
        base_url=settings.mattermost_base_url.rstrip("/"),
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"Authorization": f"Bearer {settings.mattermost_bot_token}"},
    ) as client:
        try:
            response = await client.get(f"/api/v4/users/{external_user_id}/image")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        content = response.content
    return content or None


__all__ = [
    "DM_CHANNEL_TYPE",
    "TagDirectError",
    "TagDirectListener",
    "TagDirectRejected",
    "TagDirectSender",
    "TagDirectUnknown",
    "fetch_bot_user_id",
    "fetch_tag_avatar",
    "ingest_direct_message",
    "parse_posted_event",
]
