"""Eighteenth migration: which operator sent each operator message
(owner request, 2026-11-19 — the history must show the name).

messages.author_operator_id: set on every operator reply; NULL for
user/AI/system messages (check stays: only OPERATOR rows carry it).

Revision ID: 0018_message_operator_author
Revises: 0017_sla_status_history
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0018_message_operator_author"
down_revision: str | None = "0017_sla_status_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "author_operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "author_operator_id")
