"""Invited specialists storage (owner request, 2026-11-23, plan item 7)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DialogParticipant, Operator


class ParticipantRepository:
    async def invite(
        self, session: AsyncSession, *, conversation_id: uuid.UUID, operator_id: uuid.UUID
    ) -> DialogParticipant:
        """Idempotent: an existing (possibly left) membership reactivates."""
        existing = await session.scalar(
            select(DialogParticipant)
            .where(
                DialogParticipant.conversation_id == conversation_id,
                DialogParticipant.operator_id == operator_id,
            )
            .with_for_update()
        )
        if existing is not None:
            existing.left_at = None
            await session.flush()
            return existing
        participant = DialogParticipant(
            conversation_id=conversation_id, operator_id=operator_id
        )
        session.add(participant)
        await session.flush()
        return participant

    async def leave(
        self, session: AsyncSession, *, conversation_id: uuid.UUID, operator_id: uuid.UUID
    ) -> bool:
        from datetime import UTC, datetime

        participant = await session.scalar(
            select(DialogParticipant)
            .where(
                DialogParticipant.conversation_id == conversation_id,
                DialogParticipant.operator_id == operator_id,
                DialogParticipant.left_at.is_(None),
            )
            .with_for_update()
        )
        if participant is None:
            return False
        participant.left_at = datetime.now(UTC)
        await session.flush()
        return True

    async def active_operators(
        self,
        session: AsyncSession,
        conversation_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Operator]]:
        """Active specialists per conversation (joined, not left)."""
        if not conversation_ids:
            return {}
        rows = (
            await session.execute(
                select(DialogParticipant.conversation_id, Operator)
                .join(Operator, Operator.id == DialogParticipant.operator_id)
                .where(
                    DialogParticipant.conversation_id.in_(conversation_ids),
                    DialogParticipant.left_at.is_(None),
                )
                .order_by(DialogParticipant.joined_at)
            )
        ).all()
        result: dict[uuid.UUID, list[Operator]] = {}
        for conversation_id, operator in rows:
            result.setdefault(conversation_id, []).append(operator)
        return result

    async def is_active_participant(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        operator_id: uuid.UUID,
    ) -> bool:
        return (
            await session.scalar(
                select(DialogParticipant.id).where(
                    DialogParticipant.conversation_id == conversation_id,
                    DialogParticipant.operator_id == operator_id,
                    DialogParticipant.left_at.is_(None),
                )
            )
            is not None
        )
