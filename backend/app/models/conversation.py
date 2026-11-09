"""Logical conversation and fixed 3-hour sessions (D-005/D-006/D-007/D-008)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class DialogMode(enum.StrEnum):
    AI_ACTIVE = "AI_ACTIVE"
    HUMAN_PENDING = "HUMAN_PENDING"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    CLOSED = "CLOSED"


class SessionStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    ENDED = "ENDED"


class Conversation(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Target for the composite FK tickets.(conversation_id, user_id).
        UniqueConstraint("id", "user_id", name="uq_conversation_id_user"),
        CheckConstraint("state_version > 0", name="ck_conversation_state_version"),
        CheckConstraint(
            "last_message_sequence >= 0", name="ck_conversation_last_sequence"
        ),
        Index("ix_conversations_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="RESTRICT"), nullable=True
    )
    mode: Mapped[DialogMode] = mapped_column(
        Enum(DialogMode, native_enum=False, length=20),
        nullable=False,
        default=DialogMode.AI_ACTIVE,
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
    last_message_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )


class ConversationSession(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        # Confirmed rule D-007: a session lasts exactly 3 hours, not configurable.
        CheckConstraint(
            "expires_at = started_at + interval '3 hours'",
            name="ck_session_fixed_3_hours",
        ),
        # No more than one ACTIVE session per conversation.
        Index(
            "uq_session_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False, length=20),
        nullable=False,
        default=SessionStatus.ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '3 hours'"),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
