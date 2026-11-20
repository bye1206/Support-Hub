"""Twenty-second migration: users.email (owner question, 2026-11-20).

The Tag profile carries the corp e-mail; storing it lets the AD lookup
match the person exactly by mail — the tie-breaker when two employees
share the same full name.

Revision ID: 0022_user_email
Revises: 0021_operator_presence_log
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_user_email"
down_revision: str | None = "0021_operator_presence_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email")
