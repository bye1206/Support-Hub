"""Knowledge base articles (owner request, 2026-11-23, plan item 8).

SUPERVISOR/ADMIN maintain the reference in the admin panel; operators
insert articles as reply drafts and get typing hints in the composer.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
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
