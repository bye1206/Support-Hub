"""Status history + SLA events per ticket (owner request, 2026-11-19).

Every FSM transition appends a `status` row; SLA breaches and met
deadlines append their own rows. The SLA modal in the workspace renders
this timeline and the per-status durations.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class TicketHistoryKind(enum.StrEnum):
    STATUS = "status"
    SLA_BREACHED = "sla_breached"
    SLA_MET = "sla_met"


class TicketStatusHistory(UuidPkMixin, Base):
    __tablename__ = "ticket_status_history"
    __table_args__ = (Index("ix_ticket_history_ticket", "ticket_id"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[TicketHistoryKind] = mapped_column(
        String(20), nullable=False, default=TicketHistoryKind.STATUS.value
    )
    # Null for SLA rows (they carry no status pair).
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Explicit timestamp column (no created_at updates semantics needed).
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
