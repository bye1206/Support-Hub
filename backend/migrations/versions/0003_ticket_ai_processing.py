"""Third migration: ticket status AI_PROCESSING + named status CHECK (D-039).

D-039 (owner): new status "Обработка ИИ" (AI_PROCESSING). The status column
was a plain VARCHAR without a native CHECK, so this migration adds a named
constraint `ck_ticket_status` locking the vocabulary. The FSM itself stays
in the domain layer (docs/03 §4: DB CHECKs do not replace the FSM).

Revision ID: 0003_ticket_ai_processing
Revises: 0002_outbox_integration_audit
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_ticket_ai_processing"
down_revision: str | None = "0002_outbox_integration_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TICKET_STATUSES = (
    "NEW",
    "AI_PROCESSING",
    "OPEN",
    "PENDING_USER",
    "RESOLVED",
    "CLOSED",
)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_ticket_status",
        "tickets",
        f"status IN ({', '.join(repr(value) for value in _TICKET_STATUSES)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ticket_status", "tickets", type_="check")
