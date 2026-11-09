"""Session lifecycle: fixed 3-hour sessions (D-006/D-007), lazy expiry (P-05)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationSession, SessionStatus
from app.repositories.conversations import SessionRepository

# Confirmed rule D-007: a session lasts exactly 3 hours, never configurable.
SESSION_DURATION = timedelta(hours=3)


class SessionService:
    def __init__(self, sessions: SessionRepository | None = None) -> None:
        self._sessions = sessions or SessionRepository()

    async def ensure_active(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> ConversationSession:
        """Return the dialog's usable ACTIVE session, creating one if needed.

        A session whose expires_at has passed is treated as expired on read
        (P-05 lazy guarantee) even before the worker marks it EXPIRED.
        The dialog must not be CLOSED; callers guarantee that (a message after
        CLOSED starts a new dialog, P-04).
        """
        now = datetime.now(UTC)
        active = await self._sessions.get_active(session, conversation_id)
        if active is not None:
            if active.expires_at > now:
                return active
            await self._sessions.mark(
                session, active, SessionStatus.EXPIRED, at=now
            )
        try:
            async with session.begin_nested():
                return await self._sessions.start(
                    session, conversation_id, started_at=now, duration=SESSION_DURATION
                )
        except IntegrityError:
            # Concurrent message in the same dialog created the ACTIVE session.
            winner = await self._sessions.get_active(session, conversation_id)
            if winner is None:
                raise
            return winner

    async def expire_due(self, session: AsyncSession) -> int:
        """P-05 worker step: bulk-mark sessions whose time is up (ACTIVE ->
        EXPIRED is an allowed FSM transition, so the bulk update is safe)."""
        return await self._sessions.expire_due(session, now=datetime.now(UTC))

    async def end_active(self, session: AsyncSession, conversation_id: uuid.UUID) -> None:
        """Mark the dialog's ACTIVE sessions ENDED (dialog closed, FSM-safe)."""
        await self._sessions.end_active(session, conversation_id, at=datetime.now(UTC))
