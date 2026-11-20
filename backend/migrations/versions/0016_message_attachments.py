"""Sixteenth migration: message attachments (owner request, 2026-11-19).

Files travel in both directions (user -> operator via Tag, operator ->
user with the reply). Bytes are stored on local disk (files_dir); the
table owns metadata and the message link. message_id is NULL while the
operator composes the reply (upload happens on attach) and is set when
the reply/ingress message commits.

Revision ID: 0016_message_attachments
Revises: 0015_trgm_search_indexes
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0016_message_attachments"
down_revision: str | None = "0015_trgm_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column(
            "uploaded_by_operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_attachments_conversation", "message_attachments", ["conversation_id"]
    )
    op.create_index("ix_attachments_message", "message_attachments", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_message", table_name="message_attachments")
    op.drop_index(
        "ix_attachments_conversation", table_name="message_attachments"
    )
    op.drop_table("message_attachments")
