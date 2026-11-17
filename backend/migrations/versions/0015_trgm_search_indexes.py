"""Fifteenth migration: pg_trgm indexes for history search (perf round).

The history filters do substring search (`lower(col) LIKE '%q%'`) over
user names, Tag identities and message text — plain B-tree cannot serve
those, every query was a sequential scan. GIN trigram indexes serve
LIKE '%…%' on the exact same expressions used by the queries.

Revision ID: 0015_trgm_search_indexes
Revises: 0014_hotpath_indexes
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_trgm_search_indexes"
down_revision: str | None = "0014_hotpath_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_users_display_name_trgm ON users "
        "USING gin (lower(display_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_user_identities_name_trgm ON user_identities "
        "USING gin (lower(external_user_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_messages_text_trgm ON messages "
        "USING gin (lower(text) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_user_identities_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_users_display_name_trgm")
