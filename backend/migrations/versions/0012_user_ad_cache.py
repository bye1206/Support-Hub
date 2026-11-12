"""AD employee card cache on users (P-29): jsonb snapshot, photo, sync time.

Revision ID: 0012_user_ad_cache
Revises: 0011_operator_presence
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_user_ad_cache"
down_revision: str | None = "0011_operator_presence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ad_info", JSONB, nullable=True))
    op.add_column("users", sa.Column("ad_photo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "users", sa.Column("ad_synced_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "ad_synced_at")
    op.drop_column("users", "ad_photo")
    op.drop_column("users", "ad_info")
