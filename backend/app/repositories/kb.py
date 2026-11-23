"""Knowledge base article storage (owner request, 2026-11-23, plan 8)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KbArticle, Operator


class KbRepository:
    async def list_all(self, session: AsyncSession) -> list[KbArticle]:
        stmt = select(KbArticle).order_by(KbArticle.title)
        return list((await session.scalars(stmt)).all())

    async def list_active(self, session: AsyncSession) -> list[KbArticle]:
        stmt = (
            select(KbArticle)
            .where(KbArticle.is_active.is_(True))
            .order_by(KbArticle.title)
        )
        return list((await session.scalars(stmt)).all())

    async def get(self, session: AsyncSession, article_id: uuid.UUID) -> KbArticle | None:
        return await session.get(KbArticle, article_id)

    async def create(
        self, session: AsyncSession, *, title: str, body: str, author: Operator
    ) -> KbArticle:
        article = KbArticle(title=title.strip(), body=body.strip(), created_by=author.id)
        session.add(article)
        await session.flush()
        return article

    async def delete(self, session: AsyncSession, article: KbArticle) -> None:
        await session.delete(article)
        await session.flush()
