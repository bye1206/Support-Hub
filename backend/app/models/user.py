"""User domain: end-user profile, external channel identities, corporate accounts."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class User(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cached AD employee card (P-29): JSON snapshot + photo bytes. Refreshed
    # lazily when older than ad_info_ttl_seconds; photo updates in AD reach
    # the UI within the same TTL.
    ad_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ad_photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ad_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserIdentity(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("channel_type", "external_user_id", name="uq_user_identity"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CorporateAccount(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "corporate_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "external_subject", name="uq_corporate_account"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
