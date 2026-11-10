"""ARQ worker settings: `python -m app.worker` runs it against the live Redis."""

from typing import Any

from arq import cron, func
from arq.connections import RedisSettings

from app.config import get_settings
from app.worker.tasks import expire_sessions, process_ai_runs, process_outbox


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


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
    cron_jobs = [cron(expire_sessions, minute=set(range(60)), run_at_startup=False)]

    on_startup: Any = None
    on_shutdown: Any = None
    max_jobs = 10
    job_timeout = 60


if __name__ == "__main__":
    from arq.worker import run_worker

    # arq exposes run_worker for its own WorkerSettingsBase subclassing; our
    # script-class matches the runtime contract but not the stub.
    run_worker(WorkerSettings)  # type: ignore[arg-type]
