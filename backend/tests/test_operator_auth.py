"""LDAP session authentication tests (D-047).

Real PostgreSQL + real Redis; LDAP is a fake injected via Dependencies.ldap.
Covered: session issuance and reuse (REST + WS), role mapping from groups
(OPERATOR/ADMIN + upgrade on re-login), generic 401 on any LDAP rejection,
rate limiting, fail-closed (LDAP enabled -> dev token refused), break-glass
local account, session revocation, malformed Basic headers.
"""

import asyncio
import base64
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.ldap import (
    AuthRateLimiter,
    LdapAuthenticator,
    LdapAuthFailed,
    LdapIdentity,
    LdapUnavailableError,
)
from app.config import get_settings
from app.infra.container import Dependencies
from app.infra.db import DatabaseClient
from app.infra.redis_client import RedisClient
from app.main import create_app
from app.models import Operator, OperatorRole
from app.models import PresenceStatus as OperatorPresence
from tests.conftest import TEST_DB_URL

DEV_TOKEN = "test-operator-token"


class FakeLdap:
    """Stands in for LdapAuthenticator: no network, configurable outcomes."""

    def __init__(self) -> None:
        # login -> (email, display_name, is_admin); missing login = reject.
        self.users: dict[str, tuple[str, str | None, bool]] = {}
        # Logins with the (optional) supervisor group membership (D-048).
        self.supervisors: set[str] = set()
        self.unavailable = False
        self.rate_limiter = AuthRateLimiter(max_failures=3, window_seconds=300)
        self.calls: list[str] = []

    async def check_credentials(self, login: str, password: str) -> LdapIdentity:
        self.calls.append(login)
        if self.unavailable:
            raise LdapUnavailableError("fake AD down")
        if login not in self.users or password == "wrong-password":
            raise LdapAuthFailed("fake rejection")
        email, display_name, is_admin = self.users[login]
        return LdapIdentity(
            login=login,
            email=email,
            display_name=display_name,
            is_operator=True,
            is_admin=is_admin,
            is_supervisor=login in self.supervisors,
            source="ldap",
        )


def basic(login: str, password: str) -> dict[str, str]:
    raw = f"{login}:{password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}


@pytest.fixture
def operator_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPERATOR_DEV_TOKEN", DEV_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def auth_deps():
    db = DatabaseClient(TEST_DB_URL)
    redis = RedisClient("redis://127.0.0.1:6379/0")
    ldap = FakeLdap()
    deps = Dependencies(db=db, redis=redis, ldap=ldap)  # type: ignore[arg-type]
    yield deps
    asyncio.run(db.close())
    asyncio.run(redis.close())


@pytest.fixture
def client(operator_env, auth_deps) -> TestClient:
    with TestClient(create_app(deps=auth_deps)) as test_client:
        yield test_client


def _sign_in(client: TestClient, login: str = "ivanov", password: str = "P@ss") -> dict:
    response = client.post(
        "/api/v1/operator/auth/session", headers=basic(login, password)
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.anyio
async def test_session_created_and_works_on_rest(
    client: TestClient, auth_deps, session_factory
) -> None:
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", "Иванов И.И.", False)

    data = _sign_in(client)
    assert data["operator"]["email"] == "i.ivanov@corp.tander.ru"
    assert data["operator"]["role"] == "OPERATOR"
    assert data["expires_in"] > 0

    me = client.get(
        "/api/v1/operator/me",
        headers={"Authorization": f"Bearer {data['session_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["display_name"] == "Иванов И.И."

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "i.ivanov@corp.tander.ru")
            )
        ).one()
        assert operator.role == OperatorRole.OPERATOR


@pytest.mark.anyio
async def test_admin_group_maps_to_admin_role(
    client: TestClient, auth_deps, session_factory
) -> None:
    auth_deps.ldap.users["petrov"] = ("p.petrov@corp.tander.ru", "Петров П.П.", True)

    data = _sign_in(client, login="petrov")
    assert data["operator"]["role"] == "ADMIN"

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "p.petrov@corp.tander.ru")
            )
        ).one()
        assert operator.role == OperatorRole.ADMIN


@pytest.mark.anyio
async def test_role_upgrades_on_next_login(
    client: TestClient, auth_deps, session_factory
) -> None:
    """An operator promoted into the admin group gets ADMIN on re-login."""
    auth_deps.ldap.users["sidorov"] = ("s.sidorov@corp.tander.ru", None, False)
    _sign_in(client, login="sidorov")

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "s.sidorov@corp.tander.ru")
            )
        ).one()
        assert operator.role == OperatorRole.OPERATOR

    auth_deps.ldap.users["sidorov"] = ("s.sidorov@corp.tander.ru", None, True)
    data = _sign_in(client, login="sidorov")
    assert data["operator"]["role"] == "ADMIN"


@pytest.mark.anyio
async def test_manual_supervisor_role_survives_ldap_login(
    client: TestClient, auth_deps, session_factory
) -> None:
    """Without a supervisor group DN, a manually assigned SUPERVISOR (D-048) is kept."""
    auth_deps.ldap.users["smirnov"] = ("s.smirnov@corp.tander.ru", None, False)
    async with session_factory() as session:
        session.add(
            Operator(
                email="s.smirnov@corp.tander.ru",
                display_name="Смирнов С.С.",
                role=OperatorRole.SUPERVISOR,
            )
        )
        await session.commit()

    data = _sign_in(client, login="smirnov")
    assert data["operator"]["role"] == "SUPERVISOR"

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "s.smirnov@corp.tander.ru")
            )
        ).one()
        assert operator.role == OperatorRole.SUPERVISOR


@pytest.fixture
def supervisor_group_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LDAP_GROUP_SUPERVISOR_DN", "CN=support_hub_supervisor,OU=Groups")
    yield


@pytest.mark.anyio
async def test_supervisor_group_maps_to_supervisor_role(
    supervisor_group_env, client: TestClient, auth_deps, session_factory
) -> None:
    """With the supervisor group configured (D-048), the group wins."""
    auth_deps.ldap.users["orlov"] = ("o.orlov@corp.tander.ru", None, False)
    auth_deps.ldap.supervisors.add("orlov")

    data = _sign_in(client, login="orlov")
    assert data["operator"]["role"] == "SUPERVISOR"

    # Removed from the supervisor group -> NO demotion at login (D-048):
    # roles granted/promoted stay until changed in the admin panel.
    auth_deps.ldap.supervisors.discard("orlov")
    data = _sign_in(client, login="orlov")
    assert data["operator"]["role"] == "SUPERVISOR"

    # The admin group still promotes over the supervisor group.
    auth_deps.ldap.users["orlov"] = ("o.orlov@corp.tander.ru", None, True)
    auth_deps.ldap.supervisors.add("orlov")
    data = _sign_in(client, login="orlov")
    assert data["operator"]["role"] == "ADMIN"


@pytest.mark.anyio
async def test_ldap_never_demotes_panel_granted_admin(
    client: TestClient, auth_deps, session_factory
) -> None:
    """An ADMIN granted in the panel survives logins without admin group (D-048)."""
    auth_deps.ldap.users["volkov"] = ("v.volkov@corp.tander.ru", None, False)
    async with session_factory() as session:
        session.add(
            Operator(
                email="v.volkov@corp.tander.ru",
                display_name="Волков В.В.",
                role=OperatorRole.ADMIN,
            )
        )
        await session.commit()

    data = _sign_in(client, login="volkov")
    assert data["operator"]["role"] == "ADMIN"


@pytest.mark.anyio
async def test_wrong_password_is_generic_401_and_rate_limited(
    client: TestClient, auth_deps
) -> None:
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)

    for _ in range(3):
        failed = client.post(
            "/api/v1/operator/auth/session", headers=basic("ivanov", "wrong-password")
        )
        assert failed.status_code == 401
        assert failed.json()["error"]["code"] == "OPERATOR_UNAUTHORIZED"

    limited = client.post(
        "/api/v1/operator/auth/session", headers=basic("ivanov", "wrong-password")
    )
    assert limited.status_code == 403
    assert limited.json()["error"]["code"] == "AUTH_RATE_LIMITED"


@pytest.mark.anyio
async def test_unknown_login_is_401(client: TestClient, auth_deps) -> None:
    response = client.post(
        "/api/v1/operator/auth/session", headers=basic("nobody", "P@ss")
    )
    assert response.status_code == 401
    assert "group" in response.json()["error"]["message"].lower()


@pytest.mark.anyio
async def test_ldap_outage_is_503_fail_closed(client: TestClient, auth_deps) -> None:
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)
    auth_deps.ldap.unavailable = True

    response = client.post(
        "/api/v1/operator/auth/session", headers=basic("ivanov", "P@ss")
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OPERATOR_AUTH_UNAVAILABLE"


@pytest.mark.anyio
async def test_malformed_basic_is_401(client: TestClient) -> None:
    no_header = client.post("/api/v1/operator/auth/session")
    assert no_header.status_code == 401
    not_basic = client.post(
        "/api/v1/operator/auth/session", headers={"Authorization": "Bearer whatever"}
    )
    assert not_basic.status_code == 401
    bad_b64 = client.post(
        "/api/v1/operator/auth/session",
        headers={"Authorization": "Basic !!!not-base64!!!"},
    )
    assert bad_b64.status_code == 401


@pytest.mark.anyio
async def test_presence_team_and_logout(
    client: TestClient, auth_deps, session_factory
) -> None:
    """Sign-in sets ACTIVE; presence switch and team listing; logout revokes."""
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)
    data = _sign_in(client)
    headers = {"Authorization": f"Bearer {data['session_token']}"}

    team = client.get("/api/v1/operator/team", headers=headers)
    assert team.status_code == 200
    me = next(
        member
        for member in team.json()["team"]
        if member["email"] == "i.ivanov@corp.tander.ru"
    )
    assert me["presence_status"] == "ACTIVE"

    lunch = client.post(
        "/api/v1/operator/presence", json={"status": "LUNCH"}, headers=headers
    )
    assert lunch.status_code == 200

    bad = client.post(
        "/api/v1/operator/presence", json={"status": "SLEEP"}, headers=headers
    )
    assert bad.status_code == 422

    team = client.get("/api/v1/operator/team", headers=headers)
    me = next(
        member
        for member in team.json()["team"]
        if member["email"] == "i.ivanov@corp.tander.ru"
    )
    assert me["presence_status"] == "LUNCH"

    out = client.post("/api/v1/operator/logout", headers=headers)
    assert out.status_code == 200
    assert (
        client.get("/api/v1/operator/tickets", headers=headers).status_code == 401
    )

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "i.ivanov@corp.tander.ru")
            )
        ).one()
        assert operator.presence_status == OperatorPresence.OFFLINE


@pytest.mark.anyio
async def test_session_revocation_blocks_access(
    client: TestClient, auth_deps
) -> None:
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)
    data = _sign_in(client)
    headers = {"Authorization": f"Bearer {data['session_token']}"}
    assert client.get("/api/v1/operator/tickets", headers=headers).status_code == 200

    # A fresh client: redis connections are event-loop bound, and the loop
    # that served the sign-in belongs to the TestClient portal.
    revoke_redis = RedisClient("redis://127.0.0.1:6379/0")
    try:
        from app.auth.sessions import OperatorSessions

        await OperatorSessions(revoke_redis, 60).revoke(data["session_token"])
    finally:
        await revoke_redis.close()

    revoked = client.get("/api/v1/operator/tickets", headers=headers)
    assert revoked.status_code == 401


@pytest.mark.anyio
async def test_dev_session_via_session_endpoint(
    client: TestClient, auth_deps, session_factory
) -> None:
    """Dev seam: password = OPERATOR_DEV_TOKEN issues a session too, so the
    UI login form keeps ONE code path in local environments."""
    data = _sign_in(client, login="localop", password=DEV_TOKEN)
    assert data["operator"]["email"] == "localop@local.test"
    assert data["operator"]["role"] == "ADMIN"  # dev sessions are full-access

    me = client.get(
        "/api/v1/operator/me",
        headers={"Authorization": f"Bearer {data['session_token']}"},
    )
    assert me.status_code == 200

    async with session_factory() as session:
        operator = (
            await session.scalars(
                select(Operator).where(Operator.email == "localop@local.test")
            )
        ).one()
        assert operator.role == OperatorRole.ADMIN


@pytest.mark.anyio
async def test_ldap_enabled_refuses_dev_token(
    client: TestClient, auth_deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: with LDAP on, the shared dev token must not work."""
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)
    monkeypatch.setenv("LDAP_ENABLED", "true")
    get_settings.cache_clear()
    try:
        dev = client.get(
            "/api/v1/operator/tickets",
            headers={
                "Authorization": f"Bearer {DEV_TOKEN}",
                "X-Operator-Email": "op@corp.test",
            },
        )
        assert dev.status_code == 401

        data = _sign_in(client)
        ok = client.get(
            "/api/v1/operator/tickets",
            headers={"Authorization": f"Bearer {data['session_token']}"},
        )
        assert ok.status_code == 200
    finally:
        get_settings.cache_clear()


def test_break_glass_local_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """The emergency account passes even though LDAP itself is unusable."""
    from app.config import Settings

    settings = Settings(
        auth_local_user="breakglass",
        auth_local_pass="vault-secret",
        _env_file=None,  # type: ignore[call-arg]
    )
    authenticator = LdapAuthenticator(settings)
    identity = authenticator.check_credentials_sync("breakglass", "vault-secret")
    assert identity.is_admin is True
    assert identity.source == "local"
    assert "@" in identity.email


def test_ws_unknown_token_is_rejected(client: TestClient) -> None:
    with pytest.raises(Exception):  # noqa: B017 - starlette raises on 1008
        with client.websocket_connect(f"/ws?token={uuid.uuid4().hex}"):
            pass


@pytest.mark.anyio
async def test_ws_accepts_session_token(client: TestClient, auth_deps) -> None:
    auth_deps.ldap.users["ivanov"] = ("i.ivanov@corp.tander.ru", None, False)
    data = _sign_in(client)

    with client.websocket_connect(f"/ws?token={data['session_token']}") as ws:
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
