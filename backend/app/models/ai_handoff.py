"""AI handoff events: the dialog left AI mode (docs/03 #12, D-014).

Reasons (D-043 adds the gateway trigger code as a first-class source):
- AI_REQUESTED: the gateway/LLM asked for a human (stage 6 reserved);
- OPERATOR_TRIGGER: the user's magic word returned the operator trigger code;
- MANUAL: an operator/platform action.

MVP rule (D-014): no way back to AI; at most one accepted handoff per dialog
(partial unique index in the migration).
"""

import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class HandoffReason(enum.StrEnum):
    AI_REQUESTED = "AI_REQUESTED"
    OPERATOR_TRIGGER = "OPERATOR_TRIGGER"
    MANUAL = "MANUAL"


class AiHandoff(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "ai_handoffs"
    __table_args__ = (
        # docs/03 §3: at most one ACCEPTED handoff per dialog; open events are
        # allowed to accumulate (audit), acceptance is unique.
        Index(
            "uq_ai_handoff_accepted",
            "conversation_id",
            unique=True,
            postgresql_where=text("is_accepted"),
        ),
        CheckConstraint(
            "reason IN ('AI_REQUESTED', 'OPERATOR_TRIGGER', 'MANUAL')",
            name="ck_ai_handoff_reason",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_processing_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reason: Mapped[HandoffReason] = mapped_column(String(20), nullable=False)
    # docs/03: at most one ACCEPTED handoff per dialog (operator took over).
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
