"""Twenty-first migration: operator presence log (owner request, 2026-11-20).

Every presence transition writes a CLOSED interval (status, started_at =
the previous presence_since, ended_at = now). The admin stats card sums
the intervals per status and adds the still-running interval from
operators.presence_since.

Revision ID: 0021_operator_presence_log
Revises: 0020_ticket_ratings
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0021_operator_presence_log"
down_revision: str | None = "0020_ticket_ratings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_presence_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_presence_log_operator",
        "operator_presence_log",
        ["operator_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_presence_log_operator", table_name="operator_presence_log")
    op.drop_table("operator_presence_log")
