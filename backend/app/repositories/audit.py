"""Append-only audit journal writer (docs/08 §6)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditActorType, AuditLog


class AuditRepository:
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
    ) -> AuditLog:
        entry = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
        session.add(entry)
        await session.flush()
        return entry
