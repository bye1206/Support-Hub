"""Ticket: one ticket per conversation (D-005), lifecycle per docs/01."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class TicketStatus(enum.StrEnum):
    NEW = "NEW"
    # D-039 (owner): "Обработка ИИ" — the ticket is waiting for/processing an
    # AI answer. The exact transition set (D-039) is owner-confirmed in idea,
    # per-transition details PROPOSED until the stage-4 report is confirmed.
    AI_PROCESSING = "AI_PROCESSING"
    OPEN = "OPEN"
    PENDING_USER = "PENDING_USER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Ticket(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        # One ticket -> one conversation (docs/03 §1).
        UniqueConstraint("conversation_id", name="uq_ticket_conversation"),
        # The ticket user must be the conversation user.
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["conversations.id", "conversations.user_id"],
            ondelete="RESTRICT",
            name="fk_ticket_conversation_user",
        ),
        CheckConstraint("state_version > 0", name="ck_ticket_state_version"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, native_enum=False, length=20),
        nullable=False,
        default=TicketStatus.NEW,
    )
    # Priority vocabulary is not confirmed yet (open question); free string for now.
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    # Manual assignment (stage 7); auto-assignment stays behind a flag (D-031/P-07).
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Deferred assignment (owner): when the target operator is at capacity the
    # ticket is queued here and lands on them as soon as a slot frees up.
    pending_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Main category (D-026); directory management is the admin panel (stage 9).
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
    # Operator reply SLA (owner, 2026-11-19): 15 minutes to answer. The
    # deadline is (re)armed on every user message in a human dialog and on
    # assignment; the worker flags breaches. NULL = the clock is not running.
    sla_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Rating attribution (owner, 2026-11-19): stamped at closure — AI when
    # the dialog was closed by "помогло", OPERATOR + resolver on resolve.
    # NULL (e.g. timeout closures) = no rating request.
    rating_target: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rating_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"), nullable=True
    )
