"""Constraint tests on real PostgreSQL: uniqueness, CHECKs, composite FKs."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Conversation, ConversationSession, Message, Ticket, User
from tests.helpers import seed_conversation


@pytest.fixture
async def engine(test_db_url: str):
    eng = create_async_engine(test_db_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def seeded(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    return await seed_conversation(engine)


@pytest.mark.anyio
async def test_duplicate_sequence_no_rejected(engine: AsyncEngine, seeded) -> None:
    conversation_id, user_id = seeded
    async with engine.begin() as conn:
        await conn.execute(
            insert(Message).values(
                conversation_id=conversation_id,
                sequence_no=1,
                author_type="USER",
                author_user_id=user_id,
                text="first",
            )
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                insert(Message).values(
                    conversation_id=conversation_id,
                    sequence_no=1,
                    author_type="USER",
                    author_user_id=user_id,
                    text="duplicate",
                )
            )


@pytest.mark.anyio
async def test_second_active_session_rejected(engine: AsyncEngine, seeded) -> None:
    conversation_id, _ = seeded
    async with engine.begin() as conn:
        await conn.execute(
            insert(ConversationSession).values(conversation_id=conversation_id)
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(ConversationSession).values(conversation_id=conversation_id)
            )


@pytest.mark.anyio
async def test_non_active_sessions_allowed(engine: AsyncEngine, seeded) -> None:
    """EXPIRED sessions do not block a new ACTIVE one (D-008)."""
    conversation_id, _ = seeded
    async with engine.begin() as conn:
        await conn.execute(
            insert(ConversationSession).values(
                conversation_id=conversation_id, status="EXPIRED"
            )
        )
        await conn.execute(
            insert(ConversationSession).values(
                conversation_id=conversation_id, status="ENDED"
            )
        )


@pytest.mark.anyio
async def test_session_duration_is_exactly_3_hours(engine: AsyncEngine, seeded) -> None:
    conversation_id, _ = seeded
    started = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    async with engine.begin() as conn:
        await conn.execute(
            insert(ConversationSession).values(
                conversation_id=conversation_id,
                started_at=started,
                expires_at=started + timedelta(hours=3),
            )
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(ConversationSession).values(
                    conversation_id=conversation_id,
                    started_at=started,
                    expires_at=started + timedelta(hours=2),
                )
            )


@pytest.mark.anyio
async def test_ticket_user_must_match_conversation(engine: AsyncEngine, seeded) -> None:
    conversation_id, _ = seeded
    async with engine.begin() as conn:
        other_user = await conn.execute(
            insert(User).values(display_name="Other User").returning(User.id)
        )
        other_user_id = other_user.scalar_one()
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Ticket).values(
                    conversation_id=conversation_id, user_id=other_user_id
                )
            )


@pytest.mark.anyio
async def test_second_ticket_same_conversation_rejected(
    engine: AsyncEngine, seeded
) -> None:
    conversation_id, user_id = seeded
    async with engine.begin() as conn:
        await conn.execute(
            insert(Ticket).values(conversation_id=conversation_id, user_id=user_id)
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Ticket).values(conversation_id=conversation_id, user_id=user_id)
            )


@pytest.mark.anyio
async def test_reply_across_conversations_rejected(engine: AsyncEngine, seeded) -> None:
    conversation_id, user_id = seeded
    async with engine.begin() as conn:
        second_conversation = await conn.execute(
            insert(Conversation).values(user_id=user_id).returning(Conversation.id)
        )
        second_conversation_id = second_conversation.scalar_one()
        first_message = await conn.execute(
            insert(Message)
            .values(
                conversation_id=conversation_id,
                sequence_no=1,
                author_type="USER",
                author_user_id=user_id,
                text="root",
            )
            .returning(Message.id)
        )
        first_message_id = first_message.scalar_one()
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Message).values(
                    conversation_id=second_conversation_id,
                    sequence_no=1,
                    author_type="USER",
                    author_user_id=user_id,
                    text="cross-conversation reply",
                    reply_to_message_id=first_message_id,
                )
            )


@pytest.mark.anyio
async def test_conversation_state_version_must_be_positive(engine: AsyncEngine, seeded) -> None:
    _, user_id = seeded
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Conversation).values(user_id=user_id, state_version=0)
            )


@pytest.mark.anyio
async def test_user_message_without_author_rejected(engine: AsyncEngine, seeded) -> None:
    conversation_id, _ = seeded
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Message).values(
                    conversation_id=conversation_id,
                    sequence_no=1,
                    author_type="USER",
                    text="no author",
                )
            )
