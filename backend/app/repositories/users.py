"""User + identity persistence (P-06: auto-provisioning from channel identity)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserIdentity


class UserRepository:
    async def get_by_identity(
        self,
        session: AsyncSession,
        channel_type: str,
        external_user_id: str,
    ) -> User | None:
        stmt = (
            select(User)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .where(
                UserIdentity.channel_type == channel_type,
                UserIdentity.external_user_id == external_user_id,
            )
        )
        return (await session.scalars(stmt)).first()

    async def get_or_create_with_identity(
        self,
        session: AsyncSession,
        *,
        channel_type: str,
        external_user_id: str,
        external_user_name: str | None,
    ) -> User:
        """P-06: create user + identity on first sight (race-safe via savepoint)."""
        existing = await self.get_by_identity(session, channel_type, external_user_id)
        if existing is not None:
            return existing

        user = User(display_name=external_user_name or external_user_id)
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()  # populate user.id for the identity FK
                identity = UserIdentity(
                    user_id=user.id,
                    channel_type=channel_type,
                    external_user_id=external_user_id,
                    external_user_name=external_user_name,
                )
                session.add(identity)
                await session.flush()
        except IntegrityError:
            # Concurrent first message for the same external user: reuse the winner.
            existing = await self.get_by_identity(session, channel_type, external_user_id)
            if existing is None:
                raise
            return existing
        return user

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await session.get(User, user_id)

    async def list_identities(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> list[UserIdentity]:
        stmt = select(UserIdentity).where(UserIdentity.user_id == user_id)
        return list((await session.scalars(stmt)).all())
