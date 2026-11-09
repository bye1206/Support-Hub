"""Shared test helpers: minimal valid rows."""

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Conversation, User


async def seed_conversation(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create user + conversation; return (conversation_id, user_id)."""
    async with engine.begin() as conn:
        user = await conn.execute(
            insert(User).values(display_name="Test User").returning(User.id)
        )
        user_id = user.scalar_one()
        conversation = await conn.execute(
            insert(Conversation).values(user_id=user_id).returning(Conversation.id)
        )
        conversation_id = conversation.scalar_one()
    return conversation_id, user_id
