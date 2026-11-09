"""First model group: users, identities, corporate accounts, channels,
conversations, sessions, tickets, messages (docs/03).

Revision ID: 0001_first_group
Revises:
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.models import (
    DialogMode,
    MessageAuthorType,
    MessageDeliveryState,
    SessionStatus,
    TicketStatus,
)

revision: str = "0001_first_group"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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

    op.create_table(
        "channels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("channel_type", sa.String(50), nullable=False),
        sa.Column("external_channel_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("channel_type", "external_channel_id", name="uq_channel"),
    )

    op.create_table(
        "user_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_identity_user"),
            nullable=False,
        ),
        sa.Column("channel_type", sa.String(50), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_user_name", sa.String(255), nullable=True),
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
        sa.UniqueConstraint("channel_type", "external_user_id", name="uq_user_identity"),
    )

    op.create_table(
        "corporate_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_corporate_account_user"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("external_subject", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("provider", "external_subject", name="uq_corporate_account"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_conversation_user"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="RESTRICT", name="fk_conversation_channel"),
            nullable=True,
        ),
        sa.Column(
            "mode",
            sa.Enum(DialogMode, native_enum=False, length=20),
            nullable=False,
            server_default="AI_ACTIVE",
        ),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "last_message_sequence", sa.BigInteger(), nullable=False, server_default=sa.text("0")
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
        sa.UniqueConstraint("id", "user_id", name="uq_conversation_id_user"),
        sa.CheckConstraint("state_version > 0", name="ck_conversation_state_version"),
        sa.CheckConstraint("last_message_sequence >= 0", name="ck_conversation_last_sequence"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "conversation_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT", name="fk_session_conversation"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(SessionStatus, native_enum=False, length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '3 hours'"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "expires_at = started_at + interval '3 hours'", name="ck_session_fixed_3_hours"
        ),
    )
    op.create_index(
        "uq_session_active_per_conversation",
        "conversation_sessions",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT", name="fk_ticket_conversation"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_ticket_user"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(TicketStatus, native_enum=False, length=20),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("priority", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
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
        sa.UniqueConstraint("conversation_id", name="uq_ticket_conversation"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["conversations.id", "conversations.user_id"],
            ondelete="RESTRICT",
            name="fk_ticket_conversation_user",
        ),
        sa.CheckConstraint("state_version > 0", name="ck_ticket_state_version"),
    )

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT", name="fk_message_conversation"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.BigInteger(), nullable=False),
        sa.Column(
            "author_type",
            sa.Enum(MessageAuthorType, native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_message_author_user"),
            nullable=True,
        ),
        sa.Column(
            "delivery_state",
            sa.Enum(MessageDeliveryState, native_enum=False, length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.String(255), nullable=True),
        sa.Column(
            "reply_to_message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="RESTRICT", name="fk_message_reply"),
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
        sa.UniqueConstraint("conversation_id", "sequence_no", name="uq_message_sequence"),
        sa.UniqueConstraint("conversation_id", "id", name="uq_message_conversation_id"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "reply_to_message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_reply_same_conversation",
        ),
        sa.CheckConstraint(
            "(author_type = 'USER') = (author_user_id IS NOT NULL)",
            name="ck_message_user_author",
        ),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("tickets")
    op.drop_index("uq_session_active_per_conversation", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("corporate_accounts")
    op.drop_table("user_identities")
    op.drop_table("channels")
    op.drop_table("users")
