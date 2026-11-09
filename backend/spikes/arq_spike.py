"""ARQ feasibility spike (decision D-030, status PROPOSED).

Verifies that arq imports cleanly, a worker can be constructed, and — when a
Redis is reachable at 127.0.0.1:6379 — that a task round-trips through a live
worker: enqueue -> execute -> result.

Run: python spikes/arq_spike.py
"""

import asyncio
import logging
from importlib.metadata import version

from arq.connections import RedisSettings

logging.disable(logging.CRITICAL)


async def dummy_task(ctx: dict[str, object]) -> str:
    return "arq-round-trip-ok"


class SpikeWorkerSettings:
    functions = [dummy_task]
    redis_settings = RedisSettings(host="127.0.0.1", port=6379)


async def round_trip() -> bool:
    """Enqueue a task and get the result back through a live worker, if Redis is up."""
    from arq import create_pool
    from arq.worker import create_worker

    try:
        pool = await create_pool(SpikeWorkerSettings.redis_settings)
    except Exception as exc:
        print(f"Redis unavailable, round-trip skipped: {type(exc).__name__}")
        return False

    worker = create_worker(SpikeWorkerSettings)
    if not hasattr(worker, "async_run"):
        print("arq API changed: Worker.async_run is missing; round-trip skipped")
        return False

    runner = asyncio.create_task(worker.async_run())
    try:
        job = await pool.enqueue_job("dummy_task")
        result = await job.result(timeout=10)
        print(f"ARQ round-trip result: {result}")
        return result == "arq-round-trip-ok"
    finally:
        await worker.close()
        await pool.aclose()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


def main() -> None:
    import arq
    from arq.worker import create_worker

    worker_check = create_worker(SpikeWorkerSettings)
    print(f"arq {arq.VERSION} imported OK")  # type: ignore[attr-defined]
    print(f"asyncpg {version('asyncpg')} OK")
    print(f"worker constructed OK: {type(worker_check).__name__}")
    completed = asyncio.run(round_trip())
    print("Round-trip verified." if completed else "Round-trip NOT verified.")


if __name__ == "__main__":
    main()
