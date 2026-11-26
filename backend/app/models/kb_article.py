"""Knowledge base articles (owner request, 2026-11-23, plan item 8).

SUPERVISOR/ADMIN maintain the reference in the admin panel; operators
insert articles as reply drafts and get typing hints in the composer.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
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


class KbAttachment(UuidPkMixin, TimestampMixin, Base):
    """Owner (2026-11-26): files attached to a KB article — standalone
    chips under the body and inline images via `attachment:<id>` markers
    in the text. Bytes live in the same local file storage as chat files;
    only the key is in the DB."""

    __tablename__ = "kb_attachments"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
    )
