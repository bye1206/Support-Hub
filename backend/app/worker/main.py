"""ARQ worker settings: `python -m app.worker` runs it against the live Redis."""

import logging
from typing import Any

from arq import cron, func
from arq.connections import RedisSettings

from app.config import get_settings
from app.worker.tasks import (
    _session_factory,
    check_sla_breaches,
    expire_sessions,
    process_ai_runs,
    process_outbox,
    purge_kb_archive,
    refresh_ad_info_backfill,
)

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


async def _startup(ctx: dict[str, Any]) -> None:
    """Start the Tag direct WebSocket listener HERE, in the single worker
    process (2026-11-17). It used to live in the API lifespan — with several
    uvicorn workers every process would listen and double-process DMs."""
    ctx["tag_listener"] = None
    settings = get_settings()
    if not settings.tag_direct_mode:
        return
    from app.integrations.tag.direct import (
        TagDirectListener,
        fetch_bot_user_id,
        ingest_direct_message,
    )

    factory = _session_factory(ctx)
    try:
        me = await fetch_bot_user_id(settings)
    except Exception:  # noqa: BLE001 - token problems must not stop the worker
        logger.exception("Tag direct: /users/me failed; listener not started")
        return
    if me is None:
        return
    listener = TagDirectListener(
        settings,
        factory,
        lambda fields: ingest_direct_message(factory, fields),
        me_user_id=me,
    )
    listener.start()
    ctx["tag_listener"] = listener
    logger.info("Tag direct listener started in worker (bot user %s)", me)


async def _shutdown(ctx: dict[str, Any]) -> None:
    listener = ctx.get("tag_listener")
    if listener is not None:
        await listener.stop()
        logger.info("Tag direct listener stopped")


class WorkerSettings:
    # process_ai_runs: the gateway answers in 30-60 s per dialog (contract §5),
    # one task may process up to `limit` dialogs -> generous per-task timeout;
    # max_tries=1: gateway POSTs are NOT idempotent (D-043), no auto-retries.
    functions = [
        process_outbox,
        expire_sessions,
        func(process_ai_runs, timeout=1800, max_tries=1),
    ]
    redis_settings = _redis_settings()

    # Session expiry runs every minute; expiry is idempotent (P-05).
    cron_jobs = [
        cron(expire_sessions, minute=set(range(60)), run_at_startup=False),
        # Owner request (2026-11-19): the 15-minute reply SLA — the breach
        # sweep runs every minute (idempotent: one flag per ticket).
        cron(check_sla_breaches, minute=set(range(60)), run_at_startup=False),
        # Outbox dispatch loop: nothing else enqueues process_outbox, so the
        # worker must poll by itself. Every 2 s keeps reply latency near-
        # instant (owner 2026-11-18: queue/chat updates must feel live);
        # processing is at-least-once and idempotent by idempotency_key.
        cron(process_outbox, second=set(range(0, 60, 2)), run_at_startup=True),
        # Owner report (2026-11-20): prefetch AD cards for new users so the
        # queue shows the full profile without a manual "Обновить из AD".
        cron(refresh_ad_info_backfill, minute=set(range(0, 60, 5))),
        # Owner rule (2026-11-25): the KB archive keeps deleted articles
        # for 14 days; the daily sweep purges what is older.
        cron(purge_kb_archive, hour=3, minute=17),
    ]

    on_startup: Any = _startup
    on_shutdown: Any = _shutdown
    max_jobs = 10
    job_timeout = 60


if __name__ == "__main__":
    from arq.worker import run_worker

    # arq exposes run_worker for its own WorkerSettingsBase subclassing; our
    # script-class matches the runtime contract but not the stub.
    run_worker(WorkerSettings)  # type: ignore[arg-type]