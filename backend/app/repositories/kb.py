"""Knowledge base article storage (owner request, 2026-11-23, plan 8).

Owner (2026-11-25): deletes are SOFT — deleted articles live in the
archive for KB_ARCHIVE_DAYS (the worker purges them), and every
operator can add/edit articles.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KbArticle, Operator

KB_ARCHIVE_DAYS = 14


class KbRepository:
    async def list_all(self, session: AsyncSession) -> list[KbArticle]:
        """Active reference: NOT deleted (archive is a separate listing)."""
        stmt = (
            select(KbArticle)
            .where(KbArticle.deleted_at.is_(None))
            .order_by(KbArticle.title)
        )
        return list((await session.scalars(stmt)).all())

    async def list_active(self, session: AsyncSession) -> list[KbArticle]:
        stmt = (
            select(KbArticle)
            .where(
                KbArticle.is_active.is_(True),
                KbArticle.deleted_at.is_(None),
            )
            .order_by(KbArticle.title)
        )
        return list((await session.scalars(stmt)).all())

    async def list_archive(self, session: AsyncSession) -> list[KbArticle]:
        stmt = (
            select(KbArticle)
            .where(KbArticle.deleted_at.is_not(None))
            .order_by(KbArticle.deleted_at.desc())
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

    async def soft_delete(
        self, session: AsyncSession, article: KbArticle, actor: Operator
    ) -> None:
        article.deleted_at = datetime.now(UTC)
        article.deleted_by = actor.id
        await session.flush()

    async def restore(self, session: AsyncSession, article: KbArticle) -> None:
        article.deleted_at = None
        article.deleted_by = None
        await session.flush()

    async def purge_expired(self, session: AsyncSession) -> int:
        """Hard-delete archive rows older than KB_ARCHIVE_DAYS. Worker cron."""
        cutoff = datetime.now(UTC) - timedelta(days=KB_ARCHIVE_DAYS)
        result = await session.execute(
            delete(KbArticle).where(KbArticle.deleted_at < cutoff)
        )
        return int(getattr(result, "rowcount", 0) or 0)
