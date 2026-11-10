"""Seventh migration: ticket_categories, tags, ticket_tags, tickets.category_id
(stage 7, docs/03 #22-24, D-026).

Tag names are unique case-insensitively (P-23): a unique index on lower(name);
operators attach tags by name via get_or_create. Directory management
(create/rename/delete) is the admin panel (stage 9).

Revision ID: 0007_categories_tags
Revises: 0006_internal_notes
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007_categories_tags"
down_revision: str | None = "0006_internal_notes"
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
        "ticket_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "parent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ticket_categories.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        *_timestamp_columns(),
        sa.UniqueConstraint(
            "parent_id", "name", name="uq_ticket_category_parent_name"
        ),
    )
    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        *_timestamp_columns(),
    )
    op.create_index("uq_tags_name_lower", "tags", [sa.text("lower(name)")], unique=True)
    op.create_table(
        "ticket_tags",
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ticket_categories.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_tickets_category_id", "tickets", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_category_id", table_name="tickets")
    op.drop_column("tickets", "category_id")
    op.drop_table("ticket_tags")
    op.drop_index("uq_tags_name_lower", table_name="tags")
    op.drop_table("tags")
    op.drop_table("ticket_categories")
