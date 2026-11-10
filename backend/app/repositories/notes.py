"""Internal note persistence (stage 7, docs/03 #21)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, InternalNote


class InternalNoteRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        author_id: uuid.UUID,
        body: str,
    ) -> InternalNote:
        note = InternalNote(
            conversation_id=conversation_id, author_id=author_id, body=body
        )
        session.add(note)
        await session.flush()
        return note

    async def get_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Conversation | None:
        return await session.get(Conversation, conversation_id)

    async def list_for_conversation(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> list[InternalNote]:
        stmt = (
            select(InternalNote)
            .where(InternalNote.conversation_id == conversation_id)
            .order_by(InternalNote.created_at, InternalNote.id)
        )
        return list((await session.scalars(stmt)).all())
