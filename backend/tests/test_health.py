"""Bootstrap smoke tests: health endpoints, error envelope, correlation ID."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import make_deps


def test_healthz_ok() -> None:
    client = TestClient(create_app(deps=make_deps()))
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_readyz_ok_with_healthy_deps() -> None:
    client = TestClient(create_app(deps=make_deps()))
    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {check["name"] for check in body["checks"]} == {"postgres", "redis"}


def test_unknown_route_returns_error_envelope() -> None:
    client = TestClient(create_app(deps=make_deps()))
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR"
    assert "correlation_id" in body


def test_request_id_is_echoed() -> None:
    client = TestClient(create_app(deps=make_deps()))
    response = client.get("/healthz", headers={"X-Request-ID": "test-correlation-01"})

    assert response.headers["x-request-id"] == "test-correlation-01"


def test_request_id_generated_when_absent() -> None:
    client = TestClient(create_app(deps=make_deps()))
    response = client.get("/healthz")

    assert len(response.headers["x-request-id"]) == 32  # uuid4().hex
