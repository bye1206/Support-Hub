"""Ticket category: one main category per ticket (D-026), tree per docs/03 #22.

Directory management (create/rename/parent) is the admin panel (stage 9);
this stage only needs the table plus `tickets.category_id` filtering.
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class TicketCategory(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "ticket_categories"
    __table_args__ = (
        # No duplicate names inside one parent level (docs/03 #22).
        UniqueConstraint("parent_id", "name", name="uq_ticket_category_parent_name"),
    )

    # null = top level; a child can not be moved under its own subtree
    # (checked in the service when directory management lands, stage 9).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
