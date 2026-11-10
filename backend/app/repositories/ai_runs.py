"""AI processing run persistence (docs/03 #11).

Concurrency model (D-043): at most one ACTIVE run per dialog; the worker
claims pending runs with FOR UPDATE SKIP LOCKED so several workers never take
the same dialog. Registration is deduplicated by UNIQUE (input_message_id,
attempt_no) - a re-delivered trigger event never creates a second run.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiHandoff, AiProcessingRun, AiRunStatus, HandoffReason


class AiHandoffRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        reason: HandoffReason,
        is_accepted: bool = False,
        run_id: uuid.UUID | None = None,
        summary: str | None = None,
    ) -> AiHandoff:
        """One open handoff per dialog is allowed; ACCEPTED is unique
        (partial unique index uq_ai_handoff_accepted)."""
        handoff = AiHandoff(
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            is_accepted=is_accepted,
            summary=summary,
        )
        session.add(handoff)
        await session.flush()
        return handoff

    async def get_accepted(
        self, session: AsyncSession, *, conversation_id: uuid.UUID
    ) -> AiHandoff | None:
        stmt = select(AiHandoff).where(
            AiHandoff.conversation_id == conversation_id,
            AiHandoff.is_accepted.is_(True),
        )
        return (await session.scalars(stmt)).first()


class AiRunRepository:
    async def register(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        input_message_id: uuid.UUID,
        request_id: uuid.UUID,
        attempt_no: int = 1,
    ) -> AiProcessingRun | None:
        """Create a NEW run; None when this message already has this attempt
        (idempotency primitive - the outbox is at-least-once)."""
        run = AiProcessingRun(
            conversation_id=conversation_id,
            input_message_id=input_message_id,
            attempt_no=attempt_no,
            request_id=request_id,
        )
        try:
            async with session.begin_nested():
                session.add(run)
                await session.flush()
        except IntegrityError:
            return None
        return run

    async def get(
        self, session: AsyncSession, run_id: uuid.UUID
    ) -> AiProcessingRun | None:
        return await session.get(AiProcessingRun, run_id)

    async def pending_conversation_ids(
        self, session: AsyncSession, *, limit: int = 10
    ) -> list[uuid.UUID]:
        """Dialogs with NEW runs (oldest first), one entry per dialog.

        The actual claim happens per dialog (claim_next_pending); this query
        is advisory - a dialog another worker already claimed just yields no
        claimable run.
        """
        stmt = (
            select(AiProcessingRun.conversation_id)
            .where(AiProcessingRun.status == AiRunStatus.NEW)
            .group_by(AiProcessingRun.conversation_id)
            .order_by(AiProcessingRun.conversation_id)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def claim_next_pending(
        self, session: AsyncSession, *, conversation_id: uuid.UUID
    ) -> AiProcessingRun | None:
        """Claim the oldest NEW run of the dialog (-> RUNNING).

        FOR UPDATE SKIP LOCKED: concurrent workers skip locked rows, keeping
        the "one run at a time per dialog" policy (docs/03 §3, G-11).
        """
        stmt = (
            select(AiProcessingRun)
            .where(
                AiProcessingRun.conversation_id == conversation_id,
                AiProcessingRun.status == AiRunStatus.NEW,
            )
            .order_by(AiProcessingRun.created_at, AiProcessingRun.attempt_no)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = (await session.scalars(stmt)).first()
        if run is None:
            return None
        run.status = AiRunStatus.RUNNING
        await session.flush()
        return run

    async def mark_succeeded(
        self,
        session: AsyncSession,
        run: AiProcessingRun,
        *,
        response_message_id: uuid.UUID | None = None,
        trigger_code: str | None = None,
        external_chat_id: int | None = None,
    ) -> AiProcessingRun:
        run.status = AiRunStatus.SUCCEEDED
        run.response_message_id = response_message_id
        run.trigger_code = trigger_code
        if external_chat_id is not None:
            run.external_chat_id = external_chat_id
        await session.flush()
        return run

    async def mark_failed(
        self, session: AsyncSession, run: AiProcessingRun, *, error: str
    ) -> AiProcessingRun:
        """FAILED is terminal for the run (D-043: no auto-retries - a retried
        POST would create a new gateway message). The ticket stays
        AI_PROCESSING; the operator / next user message unblocks it."""
        run.status = AiRunStatus.FAILED
        run.error = error[:2000]
        await session.flush()
        return run

    async def mark_cancelled(self, session: AsyncSession, run: AiProcessingRun) -> AiProcessingRun:
        run.status = AiRunStatus.CANCELLED
        await session.flush()
        return run

    async def cancel_pending_for_conversation(
        self, session: AsyncSession, *, conversation_id: uuid.UUID
    ) -> int:
        """NEW runs of the dialog die silently (handoff/close happened)."""
        result = await session.execute(
            update(AiProcessingRun)
            .where(
                AiProcessingRun.conversation_id == conversation_id,
                AiProcessingRun.status == AiRunStatus.NEW,
            )
            .values(status=AiRunStatus.CANCELLED)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def count_by_status(
        self,
        session: AsyncSession,
        *,
        status: AiRunStatus | None = None,
        now: datetime | None = None,
    ) -> int:
        stmt = select(AiProcessingRun)
        if status is not None:
            stmt = stmt.where(AiProcessingRun.status == status)
        return len(list((await session.scalars(stmt)).all()))
