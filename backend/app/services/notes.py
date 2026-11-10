"""Internal note service (stage 7, docs/03 #21, D-025)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditActorType, InternalNote
from app.repositories.notes import InternalNoteRepository
from app.services._tx import unit_of_work
from app.services.audit import AuditService


class NoteService:
    def __init__(
        self,
        notes: InternalNoteRepository | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._notes = notes or InternalNoteRepository()
        self._audit = audit or AuditService()

    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        author_id: uuid.UUID,
        body: str,
    ) -> InternalNote:
        """Add a private operator note. A note never changes the ticket
        status and creates no outbox event (D-025). Own transaction."""
        async with unit_of_work(session):
            conversation = await self._notes.get_conversation(session, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation {conversation_id} not found")
            note = await self._notes.create(
                session,
                conversation_id=conversation_id,
                author_id=author_id,
                body=body,
            )
            await self._audit.log(
                session,
                actor_type=AuditActorType.OPERATOR,
                action="note.created",
                entity_type="internal_note",
                entity_id=note.id,
                actor_id=author_id,
                details={"conversation_id": str(conversation_id)},
            )
            return note

    async def list(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> list[InternalNote]:
        conversation = await self._notes.get_conversation(session, conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        return await self._notes.list_for_conversation(session, conversation_id)
