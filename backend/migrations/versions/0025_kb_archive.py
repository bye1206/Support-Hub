"""Twenty-fifth migration: kb attribution + soft-delete archive (plan 8).

Operators maintain the knowledge base themselves: the article carries
who added / last edited it, and deletes are soft — the article sits in
'Недавно удалённые' for 14 days before the worker purges it.

Revision ID: 0025_kb_archive
Revises: 0024_dialog_participants
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_kb_archive"
down_revision: str | None = "0024_dialog_participants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kb_articles",
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "kb_articles",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "kb_articles",
        sa.Column(
            "deleted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("kb_articles", "deleted_by")
    op.drop_column("kb_articles", "deleted_at")
    op.drop_column("kb_articles", "updated_by")
