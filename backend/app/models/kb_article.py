"""Knowledge base articles (owner request, 2026-11-23, plan item 8).

SUPERVISOR/ADMIN maintain the reference in the admin panel; operators
insert articles as reply drafts and get typing hints in the composer.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class KbArticle(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "kb_articles"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Owner (2026-11-25): operators maintain the reference themselves —
    # the article shows who added it and who edited it last, and deletes
    # are SOFT: the article sits in 'Недавно удалённые' for 14 days
    # (restorable) before a worker purge makes it gone forever.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
