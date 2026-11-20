"""Nineteenth migration: backfill operator authors on old messages
(owner request, 2026-11-19 — the history shows the operator's name).

Operator messages sent BEFORE 0018 carry no author; the audit log knows
who acted (action=message.created, entity=message). Backfill from it.

Revision ID: 0019_backfill_operator_authors
Revises: 0018_message_operator_author
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_backfill_operator_authors"
down_revision: str | None = "0018_message_operator_author"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE messages m
        SET author_operator_id = a.actor_id
        FROM audit_logs a
        WHERE a.entity_type = 'message'
          AND a.action = 'message.created'
          AND a.entity_id = m.id
          AND m.author_type = 'OPERATOR'
          AND m.author_operator_id IS NULL
          AND a.actor_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Data backfill: nothing to revert.
    pass
