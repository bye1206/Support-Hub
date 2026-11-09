"""Audit journal service (foundation; docs/08 §6, plan stage 4)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditActorType
from app.repositories.audit import AuditRepository


class AuditService:
    """Writes audit entries inside the caller's transaction: an action and its
    audit record are committed (or rolled back) together."""

    def __init__(self, repo: AuditRepository | None = None) -> None:
        self._repo = repo or AuditRepository()

    async def log(
        self,
        session: AsyncSession,
        *,
        actor_type: AuditActorType,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._repo.log(
            session,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            details=details,
        )
