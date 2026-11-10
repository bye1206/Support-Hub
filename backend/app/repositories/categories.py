"""Ticket category persistence (stage 7; directory management is stage 9)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TicketCategory


class TicketCategoryRepository:
    async def get(
        self, session: AsyncSession, category_id: uuid.UUID
    ) -> TicketCategory | None:
        return await session.get(TicketCategory, category_id)

    async def list(self, session: AsyncSession) -> list[TicketCategory]:
        stmt = select(TicketCategory).order_by(TicketCategory.name)
        return list((await session.scalars(stmt)).all())
