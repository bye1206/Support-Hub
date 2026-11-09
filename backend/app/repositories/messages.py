"""Message persistence. Full history lives here (D-015)."""

import uuid
from datetime import datetime

from sqlalchemy import select
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
            delivery_state=delivery_state,
            text=text,
            external_post_id=external_post_id,
            source_created_at=source_created_at,
            reply_to_message_id=reply_to_message_id,
        )
        session.add(message)
        await session.flush()
        return message

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
