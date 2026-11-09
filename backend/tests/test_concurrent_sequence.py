"""Concurrent sequence allocation on real PostgreSQL.

Stage 4 will move allocation into MessageService; these tests pin the DB-level
guarantees it must rely on.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta  # noqa: F401 (used by fakes below)

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Message
from tests.helpers import seed_conversation


@pytest.fixture
async def engine(test_db_url: str):
    eng = create_async_engine(test_db_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def conversation_id(test_db_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    eng = create_async_engine(test_db_url)
    try:
        return await seed_conversation(eng)
    finally:
        await eng.dispose()


@pytest.mark.anyio
async def test_row_lock_allocates_distinct_sequences(
    test_db_url: str, conversation_id
) -> None:
    """Two concurrent writers get distinct sequence numbers via row lock."""
    conversation, user_id = conversation_id
    engine = create_async_engine(test_db_url)

    async def writer() -> int:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE conversations SET last_message_sequence = last_message_sequence + 1 "
                    "WHERE id = :cid RETURNING last_message_sequence"
                ),
                {"cid": conversation},
            )
            sequence = result.scalar_one()
            await conn.execute(
                insert(Message).values(
                    conversation_id=conversation,
                    sequence_no=sequence,
                    author_type="USER",
                    author_user_id=user_id,
                    text=f"concurrent-{sequence}",
                )
            )
            return sequence

    try:
        sequences = sorted(await asyncio.gather(writer(), writer()))
    finally:
        await engine.dispose()

    assert sequences == [1, 2]


@pytest.mark.anyio
async def test_unique_index_blocks_racing_plain_reads(
    test_db_url: str, conversation_id
) -> None:
    """Read-then-insert without locking: exactly one writer wins, one fails."""
    conversation, user_id = conversation_id
    engine = create_async_engine(test_db_url)

    async def racer(conn) -> None:
        await conn.execute(
            text("SELECT last_message_sequence FROM conversations WHERE id = :cid"),
            {"cid": conversation},
        )
        await conn.execute(
            insert(Message).values(
                conversation_id=conversation,
                sequence_no=1,
                author_type="USER",
                author_user_id=user_id,
                text="race",
            )
        )

    async def run(slot: int, results: list[BaseException | None]) -> None:
        conn = await engine.connect()
        try:
            async with conn.begin():
                await racer(conn)
        except BaseException as exc:  # noqa: BLE001 - test collects everything
            results[slot] = exc
        finally:
            await conn.close()

    results: list[BaseException | None] = [None, None]
    try:
        await asyncio.gather(run(0, results), run(1, results))
    finally:
        await engine.dispose()

    outcomes = [type(r).__name__ if r is not None else "ok" for r in results]
    assert sorted(outcomes) == ["IntegrityError", "ok"], outcomes
