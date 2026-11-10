"""AI processing runs: one gateway roundtrip per user message (docs/03 #11).

The gateway (RAG Assistant Gateway, D-043) has NO idempotency and keeps its
own context: a run is attempted once per input message; failures are NOT
auto-retried (a retried POST would create a new LLM message on their side).
The operator or the user's next message unblocks a stuck AI_PROCESSING ticket.
"""

import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class AiRunStatus(enum.StrEnum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    # The dialog left AI mode before the run started (handoff/close).
    CANCELLED = "CANCELLED"


class AiProcessingRun(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "ai_processing_runs"
    __table_args__ = (
        # One run per (input message, attempt); retries create new attempts
        # only when a future decision allows them (docs/03 §3).
        UniqueConstraint("input_message_id", "attempt_no", name="uq_ai_run_attempt"),
        CheckConstraint("attempt_no >= 1", name="ck_ai_run_attempt_no"),
        CheckConstraint("state_version > 0", name="ck_ai_run_state_version"),
        CheckConstraint(
            "status IN ('NEW', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_ai_run_status",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    input_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    status: Mapped[AiRunStatus] = mapped_column(
        Enum(AiRunStatus, native_enum=False, length=20),
        nullable=False,
        default=AiRunStatus.NEW,
    )
    # Gateway chat id (per-conversation mapping, cached on first run; D-043).
    external_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Our run correlation marker; the gateway's message id is always 0 (dummy).
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    response_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="RESTRICT"), nullable=True
    )
    # Detected gateway trigger code (D-043 §7); null for a normal answer.
    trigger_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
