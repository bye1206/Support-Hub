"""Shared fixtures: dedicated test database + Alembic upgrade/downgrade.

PostgreSQL runs via deploy/docker-compose.yml (localhost:5432).
Tests never use SQLite (AGENTS.md §6, docs/09 §6).
"""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent

ADMIN_DSN = "postgresql://support_hub:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/support_hub"
TEST_DB_NAME = "support_hub_test"
TEST_DB_URL = (
    "postgresql+asyncpg://support_hub:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/support_hub_test"
)


async def _setup_database() -> None:
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    finally:
        await conn.close()


async def _drop_database() -> None:
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_db_url() -> str:
    asyncio.run(_setup_database())
    os.environ["DATABASE_URL"] = TEST_DB_URL
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")
    yield TEST_DB_URL
    command.downgrade(config, "base")
    asyncio.run(_drop_database())
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session_factory(test_db_url: str):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(test_db_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables_between_tests(test_db_url: str):
    """Truncate all business tables after every test (integration tests share
    one database for the whole pytest session). Tolerates leaked idle-in-
    transaction connections from a faulty test: they are closed first, then
    truncate runs with a small lock_timeout."""
    yield

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _truncate() -> None:
        engine = create_async_engine(test_db_url)
        try:
            async with engine.begin() as connection:
                leaked = await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() "
                        "AND state = 'idle in transaction'"
                    )
                )
                if leaked.rowcount:  # type: ignore[attr-defined]
                    import sys

                    print(
                        f"WARNING: terminated {leaked.rowcount} leaked "
                        "idle-in-transaction connection(s); fix the leaking test.",
                        file=sys.stderr,
                    )
                await connection.execute(text("SET lock_timeout = '5s'"))
                await connection.execute(
                    text(
                        "DO $$ DECLARE r RECORD; BEGIN "
                        "FOR r IN (SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename <> 'alembic_version') "
                        "LOOP EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) "
                        "|| ' CASCADE'; END LOOP; END $$;"
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_truncate())
