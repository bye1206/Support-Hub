"""Tag persistence: case-insensitive get_or_create (P-23)."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, TicketTag


class TagRepository:
    async def get(self, session: AsyncSession, tag_id: uuid.UUID) -> Tag | None:
        return await session.get(Tag, tag_id)

    async def get_by_name(self, session: AsyncSession, name: str) -> Tag | None:
        stmt = select(Tag).where(func.lower(Tag.name) == name.lower())
        return (await session.scalars(stmt)).first()

    async def get_or_create_by_name(
        self, session: AsyncSession, *, name: str
    ) -> Tag:
        """'VPN' and 'vpn' are the same tag (P-23); race-safe."""
        existing = await self.get_by_name(session, name)
        if existing is not None:
            if not existing.is_active:
                raise ValueError(f"Tag {name} is inactive")
            return existing
        tag = Tag(name=name)
        try:
            async with session.begin_nested():
                session.add(tag)
                await session.flush()
        except IntegrityError as err:
            existing = await self.get_by_name(session, name)
            if existing is None:
                raise
            if not existing.is_active:
                raise ValueError(f"Tag {name} is inactive") from err
            return existing
        return tag

    async def link(self, session: AsyncSession, *, ticket_id: uuid.UUID, tag: Tag) -> None:
        link = TicketTag(ticket_id=ticket_id, tag_id=tag.id)
        session.add(link)
        await session.flush()

    async def unlink(
        self, session: AsyncSession, *, ticket_id: uuid.UUID, tag_id: uuid.UUID
    ) -> bool:
        """Returns True when a link was removed."""
        result = await session.execute(
            delete(TicketTag).where(
                TicketTag.ticket_id == ticket_id, TicketTag.tag_id == tag_id
            )
        )
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def list_for_ticket(
        self, session: AsyncSession, ticket_id: uuid.UUID
    ) -> list[Tag]:
        stmt = (
            select(Tag)
            .join(TicketTag, TicketTag.tag_id == Tag.id)
            .where(TicketTag.ticket_id == ticket_id)
            .order_by(func.lower(Tag.name), Tag.id)
        )
        return list((await session.scalars(stmt)).all())

    async def map_for_tickets(
        self, session: AsyncSession, ticket_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[Tag]]:
        """Tags for a batch of tickets in one query (queue view)."""
        if not ticket_ids:
            return {}
        stmt = (
            select(TicketTag.ticket_id, Tag)
            .join(Tag, Tag.id == TicketTag.tag_id)
            .where(TicketTag.ticket_id.in_(ticket_ids))
            .order_by(func.lower(Tag.name), Tag.id)
        )
        rows = (await session.execute(stmt)).all()
        result: dict[uuid.UUID, list[Tag]] = {}
        for ticket_id, tag in rows:
            result.setdefault(ticket_id, []).append(tag)
        return result
