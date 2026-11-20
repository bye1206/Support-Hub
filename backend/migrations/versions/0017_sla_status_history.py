"""Seventeenth migration: ticket status history + operator reply SLA
(owner request, 2026-11-19).

- ticket_status_history: every FSM transition (kind='status') plus SLA
  breaches ('sla_breached') and met deadlines ('sla_met');
- tickets.sla_deadline / sla_breached_at: the 15-minute operator reply
  clock; NULL = not running.

Revision ID: 0017_sla_status_history
Revises: 0016_message_attachments
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0017_sla_status_history"
down_revision: str | None = "0016_message_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_ticket_history_ticket", "ticket_status_history", ["ticket_id"]
    )
    op.add_column("tickets", sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tickets", sa.Column("sla_breached_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tickets", "sla_breached_at")
    op.drop_column("tickets", "sla_deadline")
    op.drop_index("ix_ticket_history_ticket", table_name="ticket_status_history")
    op.drop_table("ticket_status_history")
