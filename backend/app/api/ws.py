"""Workspace WebSocket: realtime events for operator clients (docs/06 §7).

Auth (P-22, PROPOSED): dev bearer token via `?token=` (the browser WebSocket
API cannot set headers). Transport: Redis pub/sub channel `support_hub:events`
- events are published by the outbox dispatcher AFTER commit (at-least-once),
clients reconcile missed updates over REST on reconnect (docs/06 §7).

Pass 2 (Keycloak): replace the token check with the OIDC flow - the
connection handler stays the same.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.infra.redis_client import EVENTS_CHANNEL

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

KEEPALIVE_SECONDS = 20.0


def _authorized(token: str | None) -> bool:
    """Dev-token check; Keycloak replaces this in pass 2 (P-22)."""
    import hmac

    settings = get_settings()
    if settings.keycloak_issuer_url or token is None:
        return False  # fail-closed: real OIDC is not wired yet
    return hmac.compare_digest(token, settings.operator_dev_token)


@router.websocket("/ws")
async def workspace_ws(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    if not _authorized(token):
        # 1008: policy violation (unauthorized) per RFC 6455.
        await websocket.close(code=1008)
        return
    await websocket.accept()

    deps = websocket.app.state.deps
    pubsub = deps.redis.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    logger.info("Workspace client connected")
    # Client-visible handshake: events published BEFORE this line would be
    # lost (pub/sub does not retain history); clients may sync over REST
    # once they see it.
    await websocket.send_text(json.dumps({"type": "ready"}))

    async def reader() -> None:
        loop = asyncio.get_running_loop()
        last_frame = loop.time()
        while True:
            try:
                # Blocks up to KEEPALIVE_SECONDS, None on silence: no busy
                # loop (get_message() default timeout is 0 = non-blocking).
                message = await pubsub.get_message(timeout=KEEPALIVE_SECONDS)
            except (asyncio.CancelledError, ConnectionError, RuntimeError):
                raise
            except Exception:
                logger.exception("Workspace reader failed")
                return
            if message is None:
                # Time-based keepalive: the first read right after
                # subscribe returns None instantly, so only a real
                # silence window produces a ping. Keeps intermediaries
                # from dropping idle connections, doubles as health check.
                now = loop.time()
                if now - last_frame >= KEEPALIVE_SECONDS:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                    last_frame = now
                continue
            payload = message.get("data")
            if isinstance(payload, bytes):
                payload = payload.decode()
            if payload:
                await websocket.send_text(payload)

    publisher_task = asyncio.create_task(reader())
    try:
        while True:
            # Client messages (pong etc.) are ignored; a disconnect breaks out.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - socket layer
        logger.info("Workspace connection closed: %s", type(exc).__name__)
    finally:
        publisher_task.cancel()
        try:
            await publisher_task
        except (asyncio.CancelledError, Exception):
            pass
        await pubsub.unsubscribe(EVENTS_CHANNEL)
        await pubsub.aclose()
        logger.info("Workspace client disconnected")
