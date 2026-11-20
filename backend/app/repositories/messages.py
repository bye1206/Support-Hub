"""Message persistence. Full history lives here (D-015)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, MessageAuthorType, MessageDeliveryState


class MessageRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        sequence_no: int,
        author_type: MessageAuthorType,
        text: str,
        author_user_id: uuid.UUID | None = None,
        author_operator_id: uuid.UUID | None = None,
        delivery_state: MessageDeliveryState = MessageDeliveryState.PENDING,
        external_post_id: str | None = None,
        source_created_at: datetime | None = None,
        reply_to_message_id: uuid.UUID | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            sequence_no=sequence_no,
            author_type=author_type,
            author_user_id=author_user_id,
            author_operator_id=author_operator_id,
            delivery_state=delivery_state,
            text=text,
            external_post_id=external_post_id,
            source_created_at=source_created_at,
            reply_to_message_id=reply_to_message_id,
        )
        session.add(message)
        await session.flush()
        return message

    async def get(self, session: AsyncSession, message_id: uuid.UUID) -> Message | None:
        return await session.get(Message, message_id)

    async def get_by_external_post_id(
        self, session: AsyncSession, external_post_id: str
    ) -> Message | None:
        """Best-effort dedup for user messages (docs/03 §3: uniqueness scope of
        external IDs is not enforced in the DB until the real Tag event model
        is confirmed; the webhook-level dedup via integration_events comes at
        stage 5)."""
        stmt = (
            select(Message)
            .where(Message.external_post_id == external_post_id)
            .order_by(Message.created_at)
            .limit(1)
        )
        return (await session.scalars(stmt)).first()

    async def list_for_conversation(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        limit: int = 100,
        after_sequence: int = 0,
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sequence_no > after_sequence,
            )
            .order_by(Message.sequence_no)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def unread_counts(
        self,
        session: AsyncSession,
        conversation_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Owner (2026-11-18): per-chat counter for the queue — how many
        user messages arrived since the last response. Owner clarified the
        reset rule: an AI reply resets the counter just like an operator's
        (both are "the dialog answered the user")."""
        if not conversation_ids:
            return {}
        last_response_seq = (
            select(
                Message.conversation_id.label("cid"),
                func.max(Message.sequence_no).label("seq"),
            )
            .where(
                Message.author_type.in_(
                    [MessageAuthorType.OPERATOR, MessageAuthorType.AI]
                )
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        rows = await session.execute(
            select(Message.conversation_id, func.count())
            .outerjoin(
                last_response_seq, last_response_seq.c.cid == Message.conversation_id
            )
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.author_type == MessageAuthorType.USER,
                Message.sequence_no > func.coalesce(last_response_seq.c.seq, 0),
            )
            .group_by(Message.conversation_id)
        )
        return {row[0]: int(row[1]) for row in rows}
