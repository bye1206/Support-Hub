"""OperatorPresenceLog model: closed presence intervals per operator.

Owner request (2026-11-20): the admin stats card shows how long the
operator was ACTIVE / on LUNCH / on BREAK. Each presence transition
writes the finished interval; the running one comes from
operators.presence_since.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class OperatorPresenceLog(UuidPkMixin, Base):
    __tablename__ = "operator_presence_log"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
