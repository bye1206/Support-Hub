"""ARQ worker tasks.

Tasks accept an optional `session_factory` in the arq context so tests can
inject a test-DB factory; production builds one from the app settings.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.tag.dispatch import build_default_outbox_handler
from app.services.outbox import OutboxService
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)

_FACTORY_KEY = "session_factory"
_HANDLER_KEY = "outbox_handler"


def _session_factory(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    factory = ctx.get(_FACTORY_KEY)
    if factory is not None:
        return factory
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def _outbox_handler(ctx: dict[str, Any]) -> Any:
    handler = ctx.get(_HANDLER_KEY)
    if handler is not None:
        return handler
    return build_default_outbox_handler()


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


async def expire_sessions(ctx: dict[str, Any]) -> int:
    """P-05: mark sessions whose 3 hours are over (does NOT touch tickets)."""
    factory = _session_factory(ctx)
    async with factory() as session:
        expired = await SessionService().expire_due(session)
        await session.commit()
    if expired:
        logger.info("Sessions expired: %s", expired)
    return expired
