"""Repository for message attachments (owner request 2026-11-19)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageAttachment


class AttachmentRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
        uploaded_by_operator_id: uuid.UUID | None = None,
    ) -> MessageAttachment:
        attachment = MessageAttachment(
            conversation_id=conversation_id,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            uploaded_by_operator_id=uploaded_by_operator_id,
        )
        session.add(attachment)
        await session.flush()
        return attachment

    async def get(
        self, session: AsyncSession, attachment_id: uuid.UUID
    ) -> MessageAttachment | None:
        return await session.get(MessageAttachment, attachment_id)

    async def for_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> list[MessageAttachment]:
        rows = await session.scalars(
            select(MessageAttachment)
            .where(MessageAttachment.conversation_id == conversation_id)
            .order_by(MessageAttachment.created_at)
        )
        return list(rows)

    async def link_to_message(
        self,
        session: AsyncSession,
        attachment_ids: list[uuid.UUID],
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> list[MessageAttachment]:
        """Attach pending uploads (message_id IS NULL) to a message."""
        linked: list[MessageAttachment] = []
        for attachment_id in attachment_ids:
            attachment = await self.get(session, attachment_id)
            if (
                attachment is None
                or attachment.conversation_id != conversation_id
                or attachment.message_id is not None
            ):
                raise ValueError(
                    f"Attachment {attachment_id} is not pending in this conversation"
                )
            attachment.message_id = message_id
            linked.append(attachment)
        return linked

    async def for_message(
        self, session: AsyncSession, message_id: uuid.UUID
    ) -> list[MessageAttachment]:
        rows = await session.scalars(
            select(MessageAttachment).where(
                MessageAttachment.message_id == message_id
            )
        )
        return list(rows)
