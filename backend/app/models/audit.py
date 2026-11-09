"""Immutable action journal (docs/03 #33, docs/08 §6).

Append-only by contract: services only INSERT. UPDATE/DELETE deny-list for the
app DB role is enforced at deployment (stage 10b).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class AuditActorType(enum.StrEnum):
    USER = "USER"
    AI = "AI"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


class AuditLog(UuidPkMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('USER', 'AI', 'OPERATOR', 'SYSTEM')",
            name="ck_audit_actor_type",
        ),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created_at", "created_at"),
    )

    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType, native_enum=False, length=20), nullable=False
    )
    # UUID of the actor row when it exists (users now, operators at stage 7);
    # SYSTEM actions have no actor row.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
