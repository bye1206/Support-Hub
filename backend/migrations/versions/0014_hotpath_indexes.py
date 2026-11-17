"""Fourteenth migration: hot-path indexes (perf round, 2026-11-17).

- messages(external_post_id): ingress dedup runs on EVERY incoming message
  and was a sequential scan;
- tickets(user_id): the client card / last-ticket routing lookup;
- tickets(assignee_id, status): operator queue counts (count_active_for);
- conversation_sessions(expires_at) WHERE status='ACTIVE': the per-minute
  expiry sweep;
- tickets(conversation_id): FK lookups (card, timeout sweep).

Revision ID: 0014_hotpath_indexes
Revises: 0013_ticket_pending_assignee
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_hotpath_indexes"
down_revision: str | None = "0013_ticket_pending_assignee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_external_post_id",
        "messages",
        ["external_post_id"],
        postgresql_where=sa.text("external_post_id IS NOT NULL"),
    )
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])
    op.create_index(
        "ix_tickets_assignee_status", "tickets", ["assignee_id", "status"]
    )
    op.create_index(
        "ix_sessions_active_expiry",
        "conversation_sessions",
        ["expires_at"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index("ix_tickets_conversation_id", "tickets", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_conversation_id", table_name="tickets")
    op.drop_index("ix_sessions_active_expiry", table_name="conversation_sessions")
    op.drop_index("ix_tickets_assignee_status", table_name="tickets")
    op.drop_index("ix_tickets_user_id", table_name="tickets")
    op.drop_index("ix_messages_external_post_id", table_name="messages")
