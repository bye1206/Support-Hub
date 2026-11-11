"""Ticket category persistence (stage 7; directory management is stage 9)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TicketCategory


class TicketCategoryRepository:
    async def get(
        self, session: AsyncSession, category_id: uuid.UUID
    ) -> TicketCategory | None:
        category = await session.get(TicketCategory, category_id)
        return category if category is not None and category.is_active else None

    async def list(self, session: AsyncSession) -> list[TicketCategory]:
        stmt = (
            select(TicketCategory)
            .where(TicketCategory.is_active.is_(True))
            .order_by(TicketCategory.name)
        )
        return list((await session.scalars(stmt)).all())
