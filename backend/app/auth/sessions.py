"""Operator session tokens (D-047): LDAP validates once, the token speaks after.

Storage: Redis key ``support_hub:session:<token>`` -> ``{"operator_id": ...}``,
fixed TTL (``auth_session_ttl_seconds``). The DB row is the source of truth on
every request (role, is_active): a deactivated operator or a role change
applies immediately, the token only proves "this operator logged in via LDAP
recently". Tokens are random 256-bit urlsafe strings; the token itself is the
secret, so Redis access equals operator access (same trust level as the app).
"""

import json
import secrets
import uuid
from dataclasses import dataclass

from app.infra.redis_client import RedisClient
from app.models import Operator

SESSION_PREFIX = "support_hub:session:"


@dataclass
class SessionRecord:
    operator_id: uuid.UUID


class OperatorSessions:
    def __init__(self, redis: RedisClient, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def create(self, operator: Operator) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"operator_id": str(operator.id)})
        await self._redis.set_string(SESSION_PREFIX + token, payload, self._ttl)
        return token

    async def resolve(self, token: str) -> SessionRecord | None:
        raw = await self._redis.get_string(SESSION_PREFIX + token)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return SessionRecord(operator_id=uuid.UUID(str(data["operator_id"])))
        except (ValueError, KeyError, TypeError):
            return None

    async def revoke(self, token: str) -> None:
        await self._redis.delete_key(SESSION_PREFIX + token)
