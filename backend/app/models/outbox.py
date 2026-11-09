"""Integration tables: transactional outbox and inbound event dedup (docs/03 #13/#14)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class OutboxStatus(enum.StrEnum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"


class IntegrationEventStatus(enum.StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"


class OutboxEvent(UuidPkMixin, TimestampMixin, Base):
    """Transactional outbox: written in the same transaction as the business change.

    A worker leases rows (SKIP LOCKED), dispatches them and marks them processed.
    Delivery to consumers is at-least-once: consumers dedup by idempotency_key.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        # Pending rows ordered by next dispatch time (NULL = immediately).
        Index(
            "ix_outbox_pending",
            "next_attempt_at",
            postgresql_where=text("status IN ('NEW', 'PROCESSING')"),
        ),
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=20),
        nullable=False,
        default=OutboxStatus.NEW,
    )
    attempts: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IntegrationEvent(UuidPkMixin, Base):
    """Inbound webhook dedup: UNIQUE (source, external_event_id) (docs/03 §3).

    Stage 5 registers every normalized Tag event here before processing.
    """

    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint("source", "external_event_id", name="uq_integration_event"),
        CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSED')", name="ck_integration_event_status"
        ),
    )

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[IntegrationEventStatus] = mapped_column(
        Enum(IntegrationEventStatus, native_enum=False, length=20),
        nullable=False,
        default=IntegrationEventStatus.RECEIVED,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
