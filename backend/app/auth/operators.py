"""Operator authentication (stage 7, pass 1 = DEV MODE, P-22 PROPOSED).

Keycloak OIDC is the target (docs/08 §1) but its parameters are not available
yet (Q-09): issuer/realm/client will be provided in the corporate network.
Until then:

- app_env=local: operators authenticate with a shared dev bearer token
  (OPERATOR_DEV_TOKEN from config, constant-time compared) and identify
  themselves by email (X-Operator-Email) - the profile auto-provisions;
- app_env != local without `keycloak_issuer_url` configured: operator
  endpoints refuse to authenticate (fail-closed), no anonymous access.

Pass 2 (Keycloak) replaces `authenticate` internals only: verify JWT
(signature/issuer/audience/exp), map sub -> operators.keycloak_sub.
"""

import hmac
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from app.config import get_settings
from app.errors import ApiError
from app.models import Operator, OperatorRole
from app.repositories.operators import OperatorRepository

DEV_AUTH_SCHEME = "DevBearer"
OPERATOR_EMAIL_HEADER = "X-Operator-Email"
OPERATOR_NAME_HEADER = "X-Operator-Name"


@dataclass
class OperatorIdentity:
    email: str
    display_name: str | None
    # Dev mode has no verified corporate subject yet (Keycloak pass 2).
    keycloak_sub: str | None = None


async def authenticate(
    authorization: str | None,
    email_header: str | None,
    name_header: str | None,
) -> OperatorIdentity:
    """Validate the request credentials; raise ApiError(401) when invalid."""
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
    if settings.keycloak_issuer_url:
        # Fail-closed until pass 2 implements real JWT verification: a half
        # configured production environment must not fall back to dev auth.
        raise ApiError(
            code="OPERATOR_AUTH_UNAVAILABLE",
            message="Keycloak authentication is not implemented yet",
            status_code=503,
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

    Deactivated operators are rejected even with valid credentials."""
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
