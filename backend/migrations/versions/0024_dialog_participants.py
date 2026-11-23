"""Twenty-fourth migration: dialog_participants (owner request, plan 7).

Invited specialists keep writing from their own profile and can leave;
the user is NOT notified. Leaving keeps the row (left_at) so a re-invite
reactivates the same membership.

Revision ID: 0024_dialog_participants
Revises: 0023_kb_articles
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_dialog_participants"
down_revision: str | None = "0023_kb_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dialog_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "conversation_id", "operator_id", name="uq_dialog_participant"
        ),
    )
    op.create_index(
        "ix_dialog_participants_conversation_id",
        "dialog_participants",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dialog_participants_conversation_id", table_name="dialog_participants"
    )
    op.drop_table("dialog_participants")
