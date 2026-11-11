"""Per-operator capacity limit for auto-assignment (D-031 refinement).

Revision ID: 0010_operator_limit
Revises: 0009_admin_directories
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_operator_limit"
down_revision: str | None = "0009_admin_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column(
            "max_active_tickets",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )


def downgrade() -> None:
    op.drop_column("operators", "max_active_tickets")
