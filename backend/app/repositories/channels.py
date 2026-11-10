"""Channel registry (Tag today): get-or-create by (channel_type, external id)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel


class ChannelRepository:
    async def get_by_external_id(
        self, session: AsyncSession, *, channel_type: str, external_channel_id: str
    ) -> Channel | None:
        stmt = select(Channel).where(
            Channel.channel_type == channel_type,
            Channel.external_channel_id == external_channel_id,
        )
        return (await session.scalars(stmt)).first()

    async def get_or_create(
        self,
        session: AsyncSession,
        *,
        channel_type: str,
        external_channel_id: str,
        display_name: str | None = None,
    ) -> Channel:
        """Create the channel row on first sight (race-safe via savepoint)."""
        existing = await self.get_by_external_id(
            session, channel_type=channel_type, external_channel_id=external_channel_id
        )
        if existing is not None:
            return existing

        channel = Channel(
            channel_type=channel_type,
            external_channel_id=external_channel_id,
            display_name=display_name,
        )
        try:
            async with session.begin_nested():
                session.add(channel)
                await session.flush()
        except IntegrityError:
            # A concurrent request registered the same channel: reuse the winner.
            existing = await self.get_by_external_id(
                session,
                channel_type=channel_type,
                external_channel_id=external_channel_id,
            )
            if existing is None:
                raise
            return existing
        return channel
