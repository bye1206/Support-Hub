"""Operator profile persistence (stage 7)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Operator, OperatorRole, Ticket, TicketStatus


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

    async def least_loaded_active(self, session: AsyncSession) -> Operator | None:
        """Active operator with the fewest non-closed assigned tickets
        (D-031 auto-assignment); oldest profile wins ties (deterministic)."""
        load = (
            select(Ticket.assignee_id.label("assignee_id"), func.count().label("load"))
            .where(
                Ticket.assignee_id.is_not(None),
                Ticket.status.not_in((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
            )
            .group_by(Ticket.assignee_id)
            .subquery()
        )
        stmt = (
            select(Operator)
            .outerjoin(load, load.c.assignee_id == Operator.id)
            .where(Operator.is_active.is_(True))
            .order_by(func.coalesce(load.c.load, 0), Operator.created_at, Operator.id)
            .limit(1)
        )
        return (await session.scalars(stmt)).first()
