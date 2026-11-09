"""Migration tests: real PostgreSQL, upgrade and downgrade paths."""

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import BACKEND_DIR

EXPECTED_TABLES = {
    "users",
    "channels",
    "user_identities",
    "corporate_accounts",
    "conversations",
    "conversation_sessions",
    "tickets",
    "messages",
}


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _tables(test_db_url: str) -> set[str]:
    async def check() -> set[str]:
        engine = create_async_engine(test_db_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )
        finally:
            await engine.dispose()

    return asyncio.run(check())


def test_upgrade_creates_all_first_group_tables(test_db_url: str) -> None:
    assert EXPECTED_TABLES.issubset(_tables(test_db_url))


def test_downgrade_then_upgrade_roundtrip(test_db_url: str) -> None:
    config = _config()

    command.downgrade(config, "base")
    try:
        assert EXPECTED_TABLES.isdisjoint(_tables(test_db_url))
    finally:
        # Restore head even if the assertion above fails: later tests need tables.
        command.upgrade(config, "head")

    assert EXPECTED_TABLES.issubset(_tables(test_db_url))
