"""Deferred ticket assignment: pending_assignee_id on tickets.

Revision ID: 0013_ticket_pending_assignee
Revises: 0012_user_ad_cache
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013_ticket_pending_assignee"
down_revision: str | None = "0012_user_ad_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("pending_assignee_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ticket_pending_assignee_operator",
        "tickets",
        "operators",
        ["pending_assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tickets_pending_assignee",
        "tickets",
        ["pending_assignee_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_pending_assignee", table_name="tickets")
    op.drop_constraint(
        "fk_ticket_pending_assignee_operator", "tickets", type_="foreignkey"
    )
    op.drop_column("tickets", "pending_assignee_id")
