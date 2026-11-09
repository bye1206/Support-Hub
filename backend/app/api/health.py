"""Health/readiness endpoints. No business logic.

/readyz performs live dependency checks (PostgreSQL, Redis) and returns 503
when any of them fails. Failure details contain no payloads — only the
exception class name and probe latency.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.infra.container import Dependencies

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str
    version: str


class ReadinessCheck(BaseModel):
    name: str
    status: str
    detail: str | None = None


class ReadinessStatus(BaseModel):
    status: str
    version: str
    checks: list[ReadinessCheck]


@router.get("/healthz", response_model=HealthStatus)
async def healthz() -> HealthStatus:
    """Liveness: the API process is up."""
    return HealthStatus(status="ok", version=__version__)


async def _run_check(
    name: str,
    probe: Callable[[], Awaitable[None]],
    timeout_seconds: float,
) -> ReadinessCheck:
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout_seconds):
            await probe()
    except Exception as exc:
        logger.warning("Readiness check failed: name=%s error=%s", name, type(exc).__name__)
        return ReadinessCheck(name=name, status="fail", detail=type(exc).__name__)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ReadinessCheck(name=name, status="ok", detail=f"{elapsed_ms}ms")


@router.get("/readyz", response_model=ReadinessStatus)
async def readyz(request: Request) -> JSONResponse:
    """Readiness: configuration plus live PostgreSQL/Redis checks."""
    deps: Dependencies = request.app.state.deps
    settings = get_settings()
    timeout = settings.readiness_timeout_seconds

    checks = list(
        await asyncio.gather(
            _run_check("postgres", deps.db.health_check, timeout),
            _run_check("redis", deps.redis.health_check, timeout),
        )
    )
    degraded = any(check.status == "fail" for check in checks)
    body = ReadinessStatus(
        status="degraded" if degraded else "ok",
        version=__version__,
        checks=checks,
    )
    return JSONResponse(status_code=503 if degraded else 200, content=body.model_dump())
