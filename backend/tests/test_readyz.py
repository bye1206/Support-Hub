"""Readiness aggregation tests: healthy, degraded, timeout, shutdown closing."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeProbe, make_deps


def test_readyz_503_when_postgres_down() -> None:
    client = TestClient(create_app(deps=make_deps(db_fail=True)))
    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    postgres_check = next(c for c in body["checks"] if c["name"] == "postgres")
    assert postgres_check["status"] == "fail"
    assert postgres_check["detail"] == "ConnectionError"
    assert {c["name"] for c in body["checks"]} == {"postgres", "redis"}


def test_readyz_503_when_redis_down() -> None:
    client = TestClient(create_app(deps=make_deps(redis_fail=True)))

    assert client.get("/readyz").status_code == 503


def test_readyz_fail_on_probe_timeout() -> None:
    deps = make_deps()
    deps.redis = FakeProbe(delay_seconds=6.0)  # exceeds readiness timeout (5s default)
    client = TestClient(create_app(deps=deps))
    response = client.get("/readyz")

    assert response.status_code == 503
    redis_check = next(c for c in response.json()["checks"] if c["name"] == "redis")
    assert redis_check["status"] == "fail"
    assert redis_check["detail"] == "TimeoutError"


def test_shutdown_closes_dependencies() -> None:
    deps = make_deps()
    with TestClient(create_app(deps=deps)):
        pass  # lifespan starts on enter, shutdown runs on exit

    assert deps.db.closed
    assert deps.redis.closed
