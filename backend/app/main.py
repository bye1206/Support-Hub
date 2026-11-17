"""FastAPI application factory.

Startup validation of settings happens in lifespan: the app refuses to start
with an invalid environment. Graceful shutdown is handled by lifespan teardown.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.operator import router as operator_router
from app.api.operator_auth import router as operator_auth_router
from app.api.tag_ingress import router as tag_ingress_router
from app.api.ws import router as ws_router
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.infra.container import Dependencies, build_dependencies
from app.logging_setup import configure_logging
from app.middleware import CorrelationIdMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()  # validates the environment
    listener = None
    if settings.tag_direct_mode:
        # Owner request 2026-11-13: direct Mattermost integration — a WebSocket
        # listener feeds bot DMs into the same ingress pipeline as the webhook.
        from app.integrations.tag.direct import (
            TagDirectListener,
            fetch_bot_user_id,
            ingest_direct_message,
        )

        try:
            me = await fetch_bot_user_id(settings)
        except Exception:  # noqa: BLE001 - token problems must not stop the API
            logger.exception("Tag direct: /users/me failed; listener not started")
            me = None
        if me is not None:
            listener = TagDirectListener(
                settings,
                app.state.deps.db.session_factory,
                lambda fields: ingest_direct_message(
                    app.state.deps.db.session_factory, fields
                ),
                me_user_id=me,
            )
            listener.start()
            logger.info("Tag direct listener started (bot user %s)", me)
    logger.info("Startup complete (env=%s, version=%s)", settings.app_env, __version__)
    yield
    if listener is not None:
        await listener.stop()
    await app.state.deps.close()
    logger.info("Shutdown complete")


def create_app(deps: Dependencies | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Support Hub API",
        version=__version__,
        # Interactive docs stay available outside production only.
        docs_url=None if settings.app_env == "prod" else "/docs",
        lifespan=lifespan,
    )
    # Engine/client construction is lazy; passing fakes is how tests inject deps.
    app.state.deps = deps if deps is not None else build_dependencies(settings)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(tag_ingress_router)
    app.include_router(operator_auth_router)
    app.include_router(operator_router)
    app.include_router(admin_router)
    app.include_router(ws_router)
    return app


app = create_app()
