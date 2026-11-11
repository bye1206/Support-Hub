"""Allow the supervisor role defined by the confirmed G-08 matrix.

Revision ID: 0008_supervisor_role
Revises: 0007_categories_tags
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_supervisor_role"
down_revision: str | None = "0007_categories_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_operator_role", "operators", type_="check")
    op.create_check_constraint(
        "ck_operator_role",
        "operators",
        "role IN ('OPERATOR', 'SUPERVISOR', 'ADMIN')",
    )


def downgrade() -> None:
    op.execute("UPDATE operators SET role = 'OPERATOR' WHERE role = 'SUPERVISOR'")
    op.drop_constraint("ck_operator_role", "operators", type_="check")
    op.create_check_constraint(
        "ck_operator_role",
        "operators",
        "role IN ('OPERATOR', 'ADMIN')",
    )
