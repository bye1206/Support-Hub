"""Twentieth migration: satisfaction ratings (owner request, 2026-11-19).

After the farewell note the user gets five buttons (5..1). A rating is
attributed to the AI (closed by "помогло") or to the operator (closed by
resolve): the target is stamped on the ticket at closure; scores 1-3
collect a free-text review. One rating per ticket.

Revision ID: 0020_ticket_ratings
Revises: 0019_backfill_operator_authors
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0020_ticket_ratings"
down_revision: str | None = "0019_backfill_operator_authors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_ratings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        # Free text for scores 1-3 ("напишите отзыв").
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # Stamped from the ticket at rating time: AI | OPERATOR.
        sa.Column("target", sa.String(16), nullable=True),
        sa.Column(
            "operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score"),
    )
    op.add_column(
        "tickets",
        sa.Column("rating_target", sa.String(16), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "rating_operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tickets", "rating_operator_id")
    op.drop_column("tickets", "rating_target")
    op.drop_table("ticket_ratings")
