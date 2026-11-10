"""Tags: free labels on tickets (docs/03 #23-24).

Names are unique case-insensitively (P-23): operators create/attach tags by
name via get_or_create, so "VPN" and "vpn" are the same tag. Directory
management (rename/delete) is the admin panel (stage 9).
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class Tag(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        # Expression index: lower-case unique name (case-insensitive match).
        Index(
            "uq_tags_name_lower",
            text("lower(name)"),
            unique=True,
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)


class TicketTag(Base):
    """Link table tickets <-> tags (docs/03 #24); composite PK, no timestamps."""

    __tablename__ = "ticket_tags"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="RESTRICT"),
        primary_key=True,
    )
