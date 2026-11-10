"""ARQ worker tasks.

Tasks accept an optional `session_factory` in the arq context so tests can
inject a test-DB factory; production builds one from the app settings.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.redis_client import EVENTS_CHANNEL
from app.integrations.tag.dispatch import RoutingOutboxHandler, build_default_outbox_handler
from app.models import OutboxEvent
from app.services.ai_runs import AiRunService, build_gateway_from_settings
from app.services.outbox import OutboxService
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)

_FACTORY_KEY = "session_factory"
_HANDLER_KEY = "outbox_handler"
_GATEWAY_KEY = "ai_gateway"


def _session_factory(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    factory = ctx.get(_FACTORY_KEY)
    if factory is not None:
        return factory
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def _outbox_handler(ctx: dict[str, Any]) -> RoutingOutboxHandler:
    handler = ctx.get(_HANDLER_KEY)
    if handler is not None:
        return handler

    async def fallback(event: OutboxEvent) -> None:
        if event.event_type == "message.user_received":
            redis = ctx.get("redis")
            message_id = (event.payload or {}).get("message_id")
            if redis is not None and message_id is not None:
                # Re-enqueue is harmless: run registration dedups by
                # (input_message_id, attempt_no).
                await redis.enqueue_job("process_ai_runs", str(message_id))
        # Realtime fan-out to workspace clients (stage 7): published after
        # commit, at-least-once; clients reconcile over REST on reconnect.
        redis_any = ctx.get("redis")
        if redis_any is not None:
            import json

            try:
                await redis_any.publish(
                    EVENTS_CHANNEL,
                    json.dumps(
                        {
                            "type": event.event_type,
                            "payload": event.payload or {},
                            "event_id": str(event.id),
                        }
                    ),
                )
            except Exception:  # noqa: BLE001 - notification, never critical
                logger.warning("WS event publish failed for %s", event.id)
        logger.info(
            "Outbox event dispatched: type=%s key=%s aggregate=%s/%s",
            event.event_type,
            event.idempotency_key,
            event.aggregate_type,
            event.aggregate_id,
        )

    default_handler = build_default_outbox_handler()
    return RoutingOutboxHandler(bot=default_handler._bot, fallback=fallback)  # noqa: SLF001


def _ai_gateway(ctx: dict[str, Any]) -> Any:
    gateway = ctx.get(_GATEWAY_KEY)
    if gateway is not None:
        return gateway
    return build_gateway_from_settings()


async def process_outbox(ctx: dict[str, Any], batch_size: int = 10) -> int:
    """Lease and dispatch pending outbox events (at-least-once)."""
    factory = _session_factory(ctx)
    async with factory() as session:
        dispatched = await OutboxService(handler=_outbox_handler(ctx)).process_batch(
            session, batch_size=batch_size
        )
    if dispatched:
        logger.info("Outbox batch dispatched: %s", dispatched)
    return dispatched


async def process_ai_runs(
    ctx: dict[str, Any], message_id: str | None = None, limit: int = 10
) -> int:
    """Stage 6: register (dedup) the run for the ingested message, then run
    every pending dialog against the gateway (synchronous, no retries)."""
    service = AiRunService(gateway=_ai_gateway(ctx))
    factory = _session_factory(ctx)
    if message_id is not None:
        conversation_id = await service.ensure_run_for_message(
            factory, uuid.UUID(message_id)
        )
        if conversation_id is None:
            return 0  # not an AI dialog / already registered
    return await service.process_pending(factory, limit=limit)


async def expire_sessions(ctx: dict[str, Any]) -> int:
    """P-05: mark sessions whose 3 hours are over (does NOT touch tickets)."""
    factory = _session_factory(ctx)
    async with factory() as session:
        expired = await SessionService().expire_due(session)
        await session.commit()
    if expired:
        logger.info("Sessions expired: %s", expired)
    return expired
