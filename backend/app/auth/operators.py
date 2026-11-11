"""Operator authentication (stage 7; D-047 LDAP sessions + dev fallback).

Pass 2 of authentication is DIRECT LDAP/AD (D-047), not Keycloak: the domain
password is accepted on POST /api/v1/operator/auth/session ONLY (HTTP Basic),
validated once via app/auth/ldap.py and exchanged for a random session token
(Redis, TTL). Every other request authenticates with that token; the DB row
stays the source of truth (role, is_active) on every call.

Dev mode (local only): shared OPERATOR_DEV_TOKEN + X-Operator-Email, used by
the automated tests and the local stack. Refused when LDAP is enabled or a
Keycloak issuer is configured (fail-closed). Keycloak OIDC remains a future
option (Q-09) - the session-token seam keeps that swap local.
"""

import hmac
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from app.auth.sessions import OperatorSessions
from app.config import get_settings
from app.errors import ApiError
from app.models import Operator, OperatorRole
from app.repositories.operators import OperatorRepository

logger = logging.getLogger(__name__)

OPERATOR_EMAIL_HEADER = "X-Operator-Email"
OPERATOR_NAME_HEADER = "X-Operator-Name"


@dataclass
class OperatorIdentity:
    email: str
    display_name: str | None
    # Dev mode has no verified corporate subject yet (Keycloak pass 2).
    keycloak_sub: str | None = None


def _dev_auth_allowed(settings: Any) -> bool:
    """Dev token is a local-development seam only (fail-closed elsewhere)."""
    return not settings.keycloak_issuer_url and not settings.ldap_enabled


async def _operator_from_session(request: Request, token: str) -> Operator | None:
    """Resolve a session token to its operator; None when not a session."""
    settings = get_settings()
    deps = request.app.state.deps
    sessions = OperatorSessions(deps.redis, settings.auth_session_ttl_seconds)
    try:
        record = await sessions.resolve(token)
    except Exception:  # noqa: BLE001 - Redis trouble: fall through to 401
        logger.warning("Session lookup failed (redis unavailable?)")
        return None
    if record is None:
        return None
    from app.infra.db import DatabaseClient

    db: DatabaseClient = deps.db
    async with db.session_factory() as session:
        operator = await OperatorRepository().get(session, record.operator_id)
    if operator is None:
        # Profile deleted after the token was issued: the token is dead.
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Session operator no longer exists",
            status_code=401,
        )
    return operator


async def authenticate(
    authorization: str | None,
    email_header: str | None,
    name_header: str | None,
) -> OperatorIdentity:
    """DEV MODE: validate the shared token + self-declared email."""
    settings = get_settings()
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not supplied or not hmac.compare_digest(
        supplied, settings.operator_dev_token
    ):
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Invalid or missing operator token",
            status_code=401,
        )
    if not _dev_auth_allowed(settings):
        # Fail-closed: LDAP/Keycloak environments must not accept dev tokens.
        raise ApiError(
            code="OPERATOR_UNAUTHORIZED",
            message="Dev-token authentication is disabled in this environment",
            status_code=401,
        )
    email = (email_header or "").strip().lower()
    if not email or "@" not in email:
        raise ApiError(
            code="OPERATOR_IDENTITY_MISSING",
            message=f"{OPERATOR_EMAIL_HEADER} header with a corporate email is required",
            status_code=401,
        )
    return OperatorIdentity(email=email, display_name=(name_header or "").strip() or None)


async def require_operator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    # FastAPI maps x_operator_email -> header "x-operator-email" (case-
    # insensitive); there is no automatic "X-" prefix.
    x_operator_email: Annotated[str | None, Header()] = None,
    x_operator_name: Annotated[str | None, Header()] = None,
) -> Operator:
    """Dependency: authenticated AND active operator (docs/08 §1).

    Order: LDAP session token (D-047) first, dev-token fallback second.
    Deactivated operators are rejected even with valid credentials."""
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if token:
        operator = await _operator_from_session(request, token)
        if operator is not None:
            return _ensure_active(operator)
    identity = await authenticate(authorization, x_operator_email, x_operator_name)
    from app.infra.db import DatabaseClient

    db: DatabaseClient = request.app.state.deps.db
    async with db.session_factory() as session:
        operator = await OperatorRepository().get_or_create_by_email(
            session,
            email=identity.email,
            display_name=identity.display_name,
            keycloak_sub=identity.keycloak_sub,
        )
        await session.commit()
    return _ensure_active(operator)


def _ensure_active(operator: Operator) -> Operator:
    if not operator.is_active:
        raise ApiError(
            code="OPERATOR_DEACTIVATED",
            message="This operator profile is deactivated",
            status_code=403,
        )
    return operator


def require_role(*roles: OperatorRole) -> Any:
    """Role gate (G-08 PROPOSED): usage - Depends(require_role(OperatorRole.ADMIN))."""

    async def _check(operator: Annotated[Operator, Depends(require_operator)]) -> Operator:
        if operator.role not in roles:
            raise ApiError(
                code="OPERATOR_FORBIDDEN",
                message="Insufficient role for this action",
                status_code=403,
            )
        return operator

    return _check


def operator_id(operator: Operator) -> uuid.UUID:
    return operator.id
