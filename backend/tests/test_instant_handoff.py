"""Owner (2026-11-23): an explicit operator request escalates instantly —
no gateway roundtrip (its worst case is a 115 s RAG timeout)."""


import pytest

from app.integrations.ai.triggers import operator_requested
from app.models import Conversation, DialogMode, TicketStatus
from tests.test_lifecycle import start_dialog


def test_operator_request_detector() -> None:
    assert operator_requested("оператор")
    assert operator_requested("Оператор!!!")
    assert operator_requested("позовите оператора")
    assert operator_requested("мне нужен специалист пожалуйста")
    assert operator_requested("живой человек")
    # A message that merely mentions an operator must NOT match.
    assert not operator_requested(
        "не работает оператор сотовой связи уже два часа"
    )
    assert not operator_requested("принтер")
    assert not operator_requested("")


@pytest.mark.anyio
async def test_operator_request_skips_the_gateway(session_factory) -> None:
    """The dialog goes HUMAN_PENDING, the ticket lands in the queue (OPEN)
    the moment the user asks for an operator — no AI run is queued."""
    async with session_factory() as session:
        result = await start_dialog(session, "оператор")

    assert result.ticket.status == TicketStatus.OPEN
    async with session_factory() as check:
        conversation = await check.get(Conversation, result.conversation.id)
        assert conversation is not None
        assert conversation.mode == DialogMode.HUMAN_PENDING
