"""Message attachments (owner request 2026-11-19).

Files travel in both directions: a USER can attach files in Tag, an
OPERATOR can attach files to a reply. Bytes live on local disk
(files_dir setting); this table owns the metadata and the message link.
An attachment is created unlinked (message_id NULL) when the operator
uploads it from the composer and linked when the reply is actually sent.
"""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class MessageAttachment(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        Index("ix_attachments_conversation", "conversation_id"),
        Index("ix_attachments_message", "message_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL until the reply (or the ingress message) that carries the file
    # is committed; unlinking is impossible once linked (RESTRICT).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Random server-side key; never derived from the user-visible name.
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
