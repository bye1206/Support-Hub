"""Fourth migration: ai_processing_runs, ai_handoffs, conversations.ai_chat_id (D-043).

The real RAG Assistant Gateway contract (owner-provided, 2026-11-10):
synchronous HTTP, no callbacks; the gateway keeps the per-chat context, so
Support Hub maps one dialog -> one gateway chat (conversations.ai_chat_id)
and tracks one run per input message (docs/03 #11: UNIQUE (input_message_id,
attempt_no)). ai_handoffs records dialog handoff events (docs/03 #12).

Revision ID: 0004_ai_runs_handoffs
Revises: 0003_ticket_ai_processing
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0004_ai_runs_handoffs"
down_revision: str | None = "0003_ticket_ai_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_STATUSES = ("NEW", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
_HANDOFF_REASONS = ("AI_REQUESTED", "OPERATOR_TRIGGER", "MANUAL")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("ai_chat_id", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "ai_processing_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "input_message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False, server_default="NEW"),
        sa.Column("external_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "response_message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("trigger_code", sa.String(30), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        *_timestamp_columns(),
        sa.UniqueConstraint("input_message_id", "attempt_no", name="uq_ai_run_attempt"),
        sa.CheckConstraint("attempt_no >= 1", name="ck_ai_run_attempt_no"),
        sa.CheckConstraint("state_version > 0", name="ck_ai_run_state_version"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in _RUN_STATUSES)})",
            name="ck_ai_run_status",
        ),
    )
    # Worker picks pending runs per dialog; leased/processed are skipped.
    op.create_index(
        "ix_ai_runs_pending",
        "ai_processing_runs",
        ["conversation_id", "created_at"],
        postgresql_where=sa.text("status = 'NEW'"),
    )

    op.create_table(
        "ai_handoffs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_processing_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("is_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("summary", sa.Text(), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"reason IN ({', '.join(repr(v) for v in _HANDOFF_REASONS)})",
            name="ck_ai_handoff_reason",
        ),
    )
    # docs/03 §3: at most one ACCEPTED handoff per dialog.
    op.create_index(
        "uq_ai_handoff_accepted",
        "ai_handoffs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("is_accepted"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_handoff_accepted", table_name="ai_handoffs")
    op.drop_table("ai_handoffs")
    op.drop_index("ix_ai_runs_pending", table_name="ai_processing_runs")
    op.drop_table("ai_processing_runs")
    op.drop_column("conversations", "ai_chat_id")
