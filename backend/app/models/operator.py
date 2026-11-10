"""Operator profile: corporate staff using the workspace (docs/03 #15).

Identity source is Keycloak (`keycloak_sub` = token `sub` claim, docs/08 §1);
the local row owns role and activity: a deactivated operator is rejected even
with a valid token. RBAC matrix itself is G-08 (PROPOSED until confirmed).
"""

import enum

from sqlalchemy import Boolean, CheckConstraint, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class OperatorRole(enum.StrEnum):
    OPERATOR = "OPERATOR"
    # Reserved for the admin panel (stage 8, docs/07); no extra rights yet.
    ADMIN = "ADMIN"


class Operator(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "operators"
    __table_args__ = (
        UniqueConstraint("email", name="uq_operator_email"),
        UniqueConstraint("keycloak_sub", name="uq_operator_keycloak_sub"),
        CheckConstraint(
            "role IN ('OPERATOR', 'ADMIN')",
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
