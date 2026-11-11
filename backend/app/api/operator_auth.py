"""Operator session endpoint (D-047): the only place domain passwords travel.

HTTP Basic with the corporate login/password is accepted HERE ONLY; LDAP
validates it once (app/auth/ldap.py) and every later REST/WS call uses a
random session token (Redis, TTL). The frontend never stores the password.
Failures are rate-limited per client IP (X-Forwarded-For only when trusted).
"""

import base64
import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.ldap import (
    LdapAuthenticator,
    LdapAuthFailed,
    LdapIdentity,
    LdapUnavailableError,
)
from app.auth.operators import require_operator
from app.auth.sessions import OperatorSessions
from app.config import get_settings
from app.errors import ApiError
from app.models import (
    AuditActorType,
    Operator,
    OperatorRole,
    PresenceStatus,
    Ticket,
)
from app.repositories.operators import OperatorRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operator", tags=["operator-auth"])

_ROLE_RANK = {
    OperatorRole.OPERATOR: 0,
    OperatorRole.SUPERVISOR: 1,
    OperatorRole.ADMIN: 2,
}


def _role_rank(role: OperatorRole) -> int:
    return _ROLE_RANK[role]


class PresenceIn(BaseModel):
    status: str = Field(pattern="^(ACTIVE|LUNCH|BREAK|OFFLINE)$")


def _basic_credentials(authorization: str | None) -> tuple[str, str]:
    if not authorization or not authorization.lower().startswith("basic "):
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="HTTP Basic credentials are required",
            status_code=401,
        )
    try:
        # UTF-8 on purpose: domain passwords may contain non-Latin letters.
        raw = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - malformed header
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Malformed Basic credentials",
            status_code=401,
        ) from exc
    login, _, password = raw.partition(":")
    if not login or not password:
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Malformed Basic credentials",
            status_code=401,
        )
    return login, password


async def _resolve_identity(
    authenticator: LdapAuthenticator,
    login: str,
    password: str,
    settings: Any,
) -> LdapIdentity:
    """Dev seam: with LDAP/Keycloak off, the shared dev token acts as the
    "domain password" so the UI keeps ONE login code path everywhere."""
    if (
        not settings.ldap_enabled
        and not settings.keycloak_issuer_url
        and hmac.compare_digest(password, settings.operator_dev_token)
    ):
        return LdapIdentity(
            login=login,
            email=f"{login}@local.test".lower(),
            display_name=login,
            is_operator=True,
            is_admin=True,
            is_supervisor=True,
            source="dev",
        )
    try:
        return await authenticator.check_credentials(login, password)
    except LdapAuthFailed as exc:
        authenticator.rate_limiter.record_failure(login)
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Invalid credentials or insufficient group membership",
            status_code=401,
        ) from exc
    except LdapUnavailableError as exc:
        # Fail-closed: AD trouble is an infrastructure failure; details go
        # to the log, the caller gets a neutral 503.
        logger.warning("LDAP unavailable during sign-in: %s", exc)
        raise ApiError(
            code="OPERATOR_AUTH_UNAVAILABLE",
            message="Authentication backend is unavailable",
            status_code=503,
        ) from exc


@router.post("/auth/session", status_code=201)
async def create_session(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Exchange corporate login/password (Basic) for a session token."""
    settings = get_settings()
    deps = request.app.state.deps
    authenticator: LdapAuthenticator = deps.ldap or LdapAuthenticator(settings)

    login, password = _basic_credentials(authorization)
    # Rate limit per LOGIN (not per IP): reliable behind nginx without
    # trusting X-Forwarded-For; brute force of one account gets throttled.
    if authenticator.rate_limiter.is_limited(login):
        raise ApiError(
            code="AUTH_RATE_LIMITED",
            message="Too many failed attempts. Try later.",
            status_code=403,
        )
    identity = await _resolve_identity(authenticator, login, password, settings)

    # LDAP groups can only PROMOTE (D-048): admin group -> ADMIN, supervisor
    # group -> SUPERVISOR, otherwise no change below the current role. Roles
    # granted in the admin panel survive every login; demotion happens only
    # in the panel (multiple DNs per group are allowed, ';'-separated).
    role = (
        OperatorRole.ADMIN
        if identity.is_admin
        else OperatorRole.SUPERVISOR
        if identity.is_supervisor
        else OperatorRole.OPERATOR
    )
    async with deps.db.session_factory() as session:
        async with unit_of_work(session):
            operator = await OperatorRepository().get_or_create_by_email(
                session,
                email=identity.email,
                display_name=identity.display_name,
            )
            if _role_rank(role) > _role_rank(operator.role):
                operator.role = role
            if identity.display_name and operator.display_name != identity.display_name:
                operator.display_name = identity.display_name
            await OperatorRepository().set_presence(
                session, operator.id, status=PresenceStatus.ACTIVE
            )
            await AuditService().log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="operator.signed_in",
                entity_type="operator",
                entity_id=operator.id,
                actor_id=operator.id,
                details={"source": identity.source, "role": str(operator.role)},
            )

    sessions = OperatorSessions(deps.redis, settings.auth_session_ttl_seconds)
    token = await sessions.create(operator)
    return {
        "session_token": token,
        "operator": {
            "operator_id": str(operator.id),
            "email": operator.email,
            "display_name": operator.display_name or operator.email,
            "role": str(operator.role),
        },
        "expires_in": settings.auth_session_ttl_seconds,
    }


@router.post("/logout")
async def logout(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """Revoke the session token and set presence OFFLINE (owner request)."""
    deps = request.app.state.deps
    settings = get_settings()
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not token:
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Session token is required",
            status_code=401,
        )
    operator_sessions = OperatorSessions(deps.redis, settings.auth_session_ttl_seconds)
    record = await operator_sessions.resolve(token)
    if record is None:
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Invalid or expired session",
            status_code=401,
        )
    await operator_sessions.revoke(token)
    async with deps.db.session_factory() as session:
        async with unit_of_work(session):
            await OperatorRepository().set_presence(
                session, record.operator_id, status=PresenceStatus.OFFLINE
            )
            await AuditService().log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="operator.signed_out",
                entity_type="operator",
                entity_id=record.operator_id,
                actor_id=record.operator_id,
            )
    return {"ok": True}


@router.post("/presence")
async def update_presence(
    payload: PresenceIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, str]:
    """Switch the operator's own status (ACTIVE/LUNCH/BREAK/OFFLINE)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        async with unit_of_work(session):
            await OperatorRepository().set_presence(
                session, operator.id, status=PresenceStatus(payload.status)
            )
            await AuditService().log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="operator.presence_changed",
                entity_type="operator",
                entity_id=operator.id,
                actor_id=operator.id,
                details={"to": payload.status},
            )
    return {"status": payload.status}


@router.get("/team")
async def team_overview(
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Presence + active ticket counts of every active operator (team panel)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        operators = await OperatorRepository().team_overview(session)
        load = (
            select(Ticket.assignee_id.label("assignee_id"), func.count().label("load"))
            .where(
                Ticket.assignee_id.is_not(None),
                Ticket.status.not_in(("RESOLVED", "CLOSED")),
            )
            .group_by(Ticket.assignee_id)
            .subquery()
        )
        counts = dict(
            (await session.execute(select(load.c.assignee_id, load.c.load))).all()
        )
    return {
        "team": [
            {
                "operator_id": str(member.id),
                "display_name": member.display_name,
                "email": member.email,
                "presence_status": str(member.presence_status),
                "presence_since": member.presence_since.isoformat(),
                "open_tickets": int(counts.get(member.id, 0)),
                "max_active_tickets": member.max_active_tickets,
            }
            for member in operators
        ]
    }
