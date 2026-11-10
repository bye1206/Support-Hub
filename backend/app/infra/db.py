"""Async PostgreSQL access via SQLAlchemy 2.x.

Models and Alembic migrations arrive at stage 3; this module only owns the
engine lifecycle and a minimal liveness probe.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


class DatabaseClient:
    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def session_factory(self) -> async_sessionmaker:
        """Sessions for service calls: one per request/worker task."""
        return self._session_factory

    async def health_check(self) -> None:
        """Raise if the database is unreachable; return otherwise."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self._engine.dispose()
