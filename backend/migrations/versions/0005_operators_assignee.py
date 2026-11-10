"""Fifth migration: operators table + tickets.assignee_id (stage 7, docs/03 #15).

Keycloak is NOT connected yet (Q-09 open): the table already carries
`keycloak_sub` for stage-7 pass 2; dev-mode authentication (P-22, PROPOSED)
auto-provisions profiles by email. `tickets.assignee_id` enables manual
assignment (D-031 auto-assignment stays behind a flag, P-07).

Revision ID: 0005_operators_assignee
Revises: 0004_ai_runs_handoffs
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005_operators_assignee"
down_revision: str | None = "0004_ai_runs_handoffs"
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
        "operators",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("keycloak_sub", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="OPERATOR"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *_timestamp_columns(),
        sa.UniqueConstraint("email", name="uq_operator_email"),
        sa.UniqueConstraint("keycloak_sub", name="uq_operator_keycloak_sub"),
        sa.CheckConstraint("role IN ('OPERATOR', 'ADMIN')", name="ck_operator_role"),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "assignee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    # Queue views filter by assignee.
    op.create_index("ix_tickets_assignee_id", "tickets", ["assignee_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_assignee_id", table_name="tickets")
    op.drop_column("tickets", "assignee_id")
    op.drop_table("operators")
