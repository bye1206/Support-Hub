"""Operator profile and locally managed RBAC roles (docs/03 #15, D-047)."""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class OperatorRole(enum.StrEnum):
    OPERATOR = "OPERATOR"
    SUPERVISOR = "SUPERVISOR"
    ADMIN = "ADMIN"


class PresenceStatus(enum.StrEnum):
    """Operator availability for new dialogs (owner request 2026-11-11)."""

    ACTIVE = "ACTIVE"
    LUNCH = "LUNCH"
    BREAK = "BREAK"
    OFFLINE = "OFFLINE"


class Operator(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "operators"
    __table_args__ = (
        UniqueConstraint("email", name="uq_operator_email"),
        UniqueConstraint("keycloak_sub", name="uq_operator_keycloak_sub"),
        CheckConstraint(
            "role IN ('OPERATOR', 'SUPERVISOR', 'ADMIN')",
            name="ck_operator_role",
        ),
    )

    # Stable business identity; auto-provisioned on first login (P-22).
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when Keycloak is connected (stage 7 pass 2); dev mode leaves it null.
    keycloak_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[OperatorRole] = mapped_column(
        Enum(OperatorRole, native_enum=False, length=20),
        nullable=False,
        default=OperatorRole.OPERATOR,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Auto-assignment capacity (D-031 refinement): the auto-router skips an
    # operator whose non-closed ticket count reached this limit. Manual
    # assignment/transfer may still exceed it (overflow lands with priority).
    max_active_tickets: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )
    # Presence: only ACTIVE operators receive auto-assigned dialogs; the
    # timer displayed to the team is computed from presence_since.
    presence_status: Mapped[PresenceStatus] = mapped_column(
        Enum(PresenceStatus, native_enum=False, length=20),
        nullable=False,
        default=PresenceStatus.ACTIVE,
        server_default="ACTIVE",
    )
    presence_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
