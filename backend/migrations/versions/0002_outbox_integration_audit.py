"""Second migration group: outbox_events, integration_events, audit_logs (docs/03 #13/#14/#33).

Revision ID: 0002_outbox_integration_audit
Revises: 0001_first_group
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models import AuditActorType, IntegrationEventStatus, OutboxStatus

revision: str = "0002_outbox_integration_audit"
down_revision: str | None = "0001_first_group"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ_COLUMNS = ("created_at", "updated_at")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )
        for name in TIMESTAMPTZ_COLUMNS
    ]


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(OutboxStatus, native_enum=False, length=20),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("attempts", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('NEW', 'PROCESSING')"),
    )

    op.create_table(
        "integration_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(IntegrationEventStatus, native_enum=False, length=20),
            nullable=False,
            server_default="RECEIVED",
        ),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source", "external_event_id", name="uq_integration_event"),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSED')", name="ck_integration_event_status"
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum(AuditActorType, native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('USER', 'AI', 'OPERATOR', 'SYSTEM')",
            name="ck_audit_actor_type",
        ),
    )
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("integration_events")
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
