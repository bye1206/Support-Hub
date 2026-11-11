"""Add soft-deactivation to category and tag dictionaries.

Revision ID: 0009_admin_directories
Revises: 0008_supervisor_role
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_admin_directories"
down_revision: str | None = "0008_supervisor_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_categories",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tags",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("tags", "is_active")
    op.drop_column("ticket_categories", "is_active")
