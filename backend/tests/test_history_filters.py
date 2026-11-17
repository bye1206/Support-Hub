"""History-page filters of the operator queue (stage 9 round 5)."""

import uuid

import pytest

from app.models import Channel, Conversation, Ticket, TicketStatus, User, UserIdentity
from app.repositories.tickets import TicketRepository


async def make_ticket(
    session_factory, *, display_name: str, ext_name: str | None, offset_days: int = 0
) -> tuple[uuid.UUID, uuid.UUID]:
    """(ticket_id, user_id)"""
    async with session_factory() as session:
        user = User(display_name=display_name)
        session.add(user)
        await session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                channel_type="tag",
                external_user_id=f"ext-{display_name}",
                external_user_name=ext_name,
            )
        )
        channel = Channel(channel_type="tag", external_channel_id=f"chan-{display_name}")
        session.add(channel)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel_id=channel.id)
        session.add(conversation)
        await session.flush()
        ticket = Ticket(conversation_id=conversation.id, user_id=user.id)
        session.add(ticket)
        await session.commit()
        return ticket.id, user.id


@pytest.mark.anyio
async def test_user_query_matches_login_and_display_name(session_factory) -> None:
    ticket_a, user_a = await make_ticket(
        session_factory, display_name="Anna Smirnova", ext_name="a.smirnova"
    )
    ticket_b, _user_b = await make_ticket(
        session_factory, display_name="Boris Volkov", ext_name="b.volkov"
    )

    repo = TicketRepository()
    async with session_factory() as session:
        by_login = await repo.list_filtered(session, user_query="smirnova")
        by_name = await repo.list_filtered(session, user_query="boris")
        by_uuid = await repo.list_filtered(session, user_query=str(user_a))
    assert [t.id for t in by_login] == [ticket_a]
    assert [t.id for t in by_name] == [ticket_b]
    assert [t.id for t in by_uuid] == [ticket_a]


@pytest.mark.anyio
async def test_ticket_query_matches_short_id(session_factory) -> None:
    ticket_id, _user = await make_ticket(
        session_factory, display_name="Anna Smirnova", ext_name="a.smirnova"
    )
    prefix = str(ticket_id).replace("-", "")[:6]

    async with session_factory() as session:
        found = await TicketRepository().list_filtered(session, ticket_query=prefix)
        by_full_uuid = await TicketRepository().list_filtered(
            session, ticket_query=str(ticket_id)
        )
    assert [t.id for t in found] == [ticket_id]
    assert [t.id for t in by_full_uuid] == [ticket_id]


@pytest.mark.anyio
async def test_status_filter_still_works(session_factory) -> None:
    await make_ticket(session_factory, display_name="Anna Smirnova", ext_name="a.smirnova")
    async with session_factory() as session:
        fresh = await TicketRepository().list_filtered(
            session, status=TicketStatus.NEW
        )
        resolved = await TicketRepository().list_filtered(
            session, status=TicketStatus.RESOLVED
        )
    assert len(fresh) == 1
    assert resolved == []
