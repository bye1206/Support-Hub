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

from fastapi import APIRouter, Header, Request

from app.auth.ldap import (
    LdapAuthenticator,
    LdapAuthFailed,
    LdapIdentity,
    LdapUnavailableError,
)
from app.auth.sessions import OperatorSessions
from app.config import get_settings
from app.errors import ApiError
from app.models import AuditActorType, OperatorRole
from app.repositories.operators import OperatorRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operator", tags=["operator-auth"])


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

    # LDAP admin group promotes to ADMIN; otherwise LDAP maps to OPERATOR,
    # except a manually assigned SUPERVISOR role (D-048), which is never demoted.
    role = OperatorRole.ADMIN if identity.is_admin else OperatorRole.OPERATOR
    async with deps.db.session_factory() as session:
        async with unit_of_work(session):
            operator = await OperatorRepository().get_or_create_by_email(
                session,
                email=identity.email,
                display_name=identity.display_name,
            )
            if operator.role != role:
                if identity.is_admin or operator.role != OperatorRole.SUPERVISOR:
                    operator.role = role
            if identity.display_name and operator.display_name != identity.display_name:
                operator.display_name = identity.display_name
            await AuditService().log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="operator.signed_in",
                entity_type="operator",
                entity_id=operator.id,
                actor_id=operator.id,
                details={"source": identity.source, "role": str(role)},
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
