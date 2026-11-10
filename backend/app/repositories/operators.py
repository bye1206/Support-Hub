"""Operator profile persistence (stage 7)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Operator, OperatorRole


class OperatorRepository:
    async def get(
        self, session: AsyncSession, operator_id: uuid.UUID
    ) -> Operator | None:
        return await session.get(Operator, operator_id)

    async def get_by_email(self, session: AsyncSession, email: str) -> Operator | None:
        stmt = select(Operator).where(Operator.email == email)
        return (await session.scalars(stmt)).first()

    async def get_or_create_by_email(
        self,
        session: AsyncSession,
        *,
        email: str,
        display_name: str | None = None,
        keycloak_sub: str | None = None,
    ) -> Operator:
        """Auto-provision the operator profile on first sign-in (P-22).

        Dev mode: identity = email from the authenticated request; Keycloak
        mode (pass 2): email + sub from the verified token. Race-safe."""
        existing = await self.get_by_email(session, email)
        if existing is not None:
            return existing
        operator = Operator(
            email=email,
            display_name=display_name,
            keycloak_sub=keycloak_sub,
            role=OperatorRole.OPERATOR,
            is_active=True,
        )
        try:
            async with session.begin_nested():
                session.add(operator)
                await session.flush()
        except IntegrityError:
            existing = await self.get_by_email(session, email)
            if existing is None:
                raise
            return existing
        return operator

    async def list_active(self, session: AsyncSession) -> list[Operator]:
        stmt = select(Operator).where(Operator.is_active.is_(True))
        return list((await session.scalars(stmt)).all())
