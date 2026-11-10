"""Internal note: private operator remark on a dialog (docs/03 #21, D-025).

Structurally separated from `messages`: a note is never a message, so it can
not be published to Tag or AI even under a filtering bug (docs/08 §5).
"""

import uuid

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class InternalNote(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "internal_notes"
    __table_args__ = (
        Index("ix_internal_notes_conversation_id", "conversation_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The author is always an operator (docs/03 #21).
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
