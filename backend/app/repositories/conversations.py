"""Conversation and session persistence."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import StateConflict
from app.models import Conversation, ConversationSession, DialogMode, SessionStatus


class ConversationRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        channel_id: uuid.UUID | None = None,
    ) -> Conversation:
        conversation = Conversation(user_id=user_id, channel_id=channel_id)
        session.add(conversation)
        await session.flush()
        return conversation

    async def get(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> Conversation | None:
        return await session.get(Conversation, conversation_id)

    async def allocate_sequence(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> int:
        """Atomically reserve the next message number (row lock, G-10)."""
        result = await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(last_message_sequence=Conversation.last_message_sequence + 1)
            .returning(Conversation.last_message_sequence)
        )
        sequence = result.scalar_one_or_none()
        if sequence is None:
            raise StateConflict(f"Conversation {conversation_id} disappeared")
        return int(sequence)

    async def change_mode(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        from_mode: DialogMode,
        to_mode: DialogMode,
        expected_state_version: int,
    ) -> int:
        """Optimistic mode change; returns the new state_version (R-05 base)."""
        result = await session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.state_version == expected_state_version,
            )
            .values(mode=to_mode, state_version=Conversation.state_version + 1)
            .returning(Conversation.state_version)
        )
        new_version = result.scalar_one_or_none()
        if new_version is None:
            raise StateConflict(
                f"Conversation {conversation_id} changed concurrently"
            )
        return int(new_version)


class SessionRepository:
    async def get_active(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> ConversationSession | None:
        stmt = (
            select(ConversationSession)
            .where(
                ConversationSession.conversation_id == conversation_id,
                ConversationSession.status == SessionStatus.ACTIVE,
            )
            .limit(1)
        )
        return (await session.scalars(stmt)).first()

    async def start(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        started_at: datetime,
        duration: timedelta,
    ) -> ConversationSession:
        """Insert an ACTIVE session; partial UNIQUE forbids a second ACTIVE one."""
        conversation_session = ConversationSession(
            conversation_id=conversation_id,
            status=SessionStatus.ACTIVE,
            started_at=started_at,
            expires_at=started_at + duration,
        )
        session.add(conversation_session)
        await session.flush()
        return conversation_session

    async def mark(
        self,
        session: AsyncSession,
        conversation_session: ConversationSession,
        status: SessionStatus,
        *,
        at: datetime,
    ) -> ConversationSession:
        conversation_session.status = status
        conversation_session.ended_at = at
        await session.flush()
        return conversation_session

    async def expire_due(self, session: AsyncSession, *, now: datetime) -> int:
        """P-05 worker step: mark every ACTIVE session past its expires_at."""
        result = await session.execute(
            update(ConversationSession)
            .where(
                ConversationSession.status == SessionStatus.ACTIVE,
                ConversationSession.expires_at <= now,
            )
            .values(status=SessionStatus.EXPIRED, ended_at=now)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def end_active(
        self, session: AsyncSession, conversation_id: uuid.UUID, *, at: datetime
    ) -> int:
        """Mark all ACTIVE sessions of the dialog ENDED (dialog closed)."""
        result = await session.execute(
            update(ConversationSession)
            .where(
                ConversationSession.conversation_id == conversation_id,
                ConversationSession.status == SessionStatus.ACTIVE,
            )
            .values(status=SessionStatus.ENDED, ended_at=at)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
