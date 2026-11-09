"""Service layer: business rules and transaction boundaries.

Transaction ownership: methods called by API/worker (top-level operations)
open and commit the transaction via `unit_of_work`; helper methods called by
other services run inside the caller's transaction and never commit.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def unit_of_work(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Commit on success, rollback on failure. Nesting-safe only at entry points."""
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
