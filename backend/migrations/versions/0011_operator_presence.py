"""Operator presence statuses: ACTIVE receives auto-assigned dialogs.

Revision ID: 0011_operator_presence
Revises: 0010_operator_limit
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_operator_presence"
down_revision: str | None = "0010_operator_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column(
            "presence_status",
            sa.String(length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column(
        "operators",
        sa.Column(
            "presence_since",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("operators", "presence_since")
    op.drop_column("operators", "presence_status")
