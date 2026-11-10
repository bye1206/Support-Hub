"""Sixth migration: internal_notes (stage 7, docs/03 #21, D-025).

Notes live on the conversation and are structurally separate from `messages`:
a note is never published to Tag or AI (docs/08 §5).

Revision ID: 0006_internal_notes
Revises: 0005_operators_assignee
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006_internal_notes"
down_revision: str | None = "0005_operators_assignee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    op.create_table(
        "internal_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        *_timestamp_columns(),
    )
    op.create_index(
        "ix_internal_notes_conversation_id", "internal_notes", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_internal_notes_conversation_id", table_name="internal_notes"
    )
    op.drop_table("internal_notes")
