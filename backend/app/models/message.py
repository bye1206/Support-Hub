"""Public messages. Support Hub owns the full history (D-015).

Internal operator notes are NOT here - separate table at a later stage
(D-025: notes are never public messages).
"""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class MessageAuthorType(enum.StrEnum):
    USER = "USER"
    AI = "AI"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


# PROPOSED delivery vocabulary; final states must be reconciled with the bot
# contract at stage 5 (docs/03 §5: delivery states are explicitly under review).
class MessageDeliveryState(enum.StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Message(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Ordering inside a conversation is by sequence_no (docs/06 §3).
        UniqueConstraint("conversation_id", "sequence_no", name="uq_message_sequence"),
        # Target for the composite FK reply.(conversation_id, reply_to_message_id).
        UniqueConstraint("conversation_id", "id", name="uq_message_conversation_id"),
        # A reply must target a message of the same conversation.
        ForeignKeyConstraint(
            ["conversation_id", "reply_to_message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_reply_same_conversation",
        ),
        # A USER message must reference its author; AI/SYSTEM must not.
        CheckConstraint(
            "(author_type = 'USER') = (author_user_id IS NOT NULL)",
            name="ck_message_user_author",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_type: Mapped[MessageAuthorType] = mapped_column(
        Enum(MessageAuthorType, native_enum=False, length=20), nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    delivery_state: Mapped[MessageDeliveryState] = mapped_column(
        Enum(MessageDeliveryState, native_enum=False, length=20),
        nullable=False,
        default=MessageDeliveryState.PENDING,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Creation time as reported by the external channel (Tag timestamp, units open).
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # External post ID in Tag; uniqueness scope is deliberately not enforced yet
    # (docs/03 §3 - must be reconciled with the real Tag event model at stage 5).
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="RESTRICT"),
        nullable=True,
    )
