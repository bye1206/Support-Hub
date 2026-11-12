"""Unit tests of the domain FSMs: every allowed transition and key rejections.

Pure functions, no DB (fast: the whole matrix is covered here).
Ticket statuses follow the owner decision D-039 (AI_PROCESSING = "Обработка
ИИ"); per-transition details are PROPOSED until the stage-4 report is
confirmed.
"""

import pytest

from app.domain.exceptions import TransitionNotAllowed
from app.domain.state_machines import (
    DialogTrigger,
    SessionTrigger,
    TicketTrigger,
    next_dialog_mode,
    next_session_status,
    next_ticket_status,
)

ALLOWED_TICKET = [
    # User message (D-039): the AI dialog goes to "Обработка ИИ".
    ("NEW", TicketTrigger.USER_MESSAGE, "AI_PROCESSING"),
    ("AI_PROCESSING", TicketTrigger.USER_MESSAGE, "AI_PROCESSING"),  # no-op
    ("OPEN", TicketTrigger.USER_MESSAGE, "AI_PROCESSING"),
    # ...except in human mode: the AI is out of the loop, the message
    # targets OPEN ("В работе") from any status (stage 9 round 4).
    ("NEW", TicketTrigger.USER_MESSAGE, "OPEN", "HUMAN_ACTIVE"),
    ("AI_PROCESSING", TicketTrigger.USER_MESSAGE, "OPEN", "HUMAN_ACTIVE"),
    ("OPEN", TicketTrigger.USER_MESSAGE, "OPEN", "HUMAN_ACTIVE"),
    ("PENDING_USER", TicketTrigger.USER_MESSAGE, "OPEN"),
    ("OPEN", TicketTrigger.USER_MESSAGE, "OPEN", "HUMAN_PENDING"),
    # AI reply (D-039: completes processing) and no-op on open.
    ("AI_PROCESSING", TicketTrigger.AI_REPLY, "OPEN"),
    ("OPEN", TicketTrigger.AI_REPLY, "OPEN"),
    # Operator reply -> PENDING_USER (D-011), from any non-terminal status;
    # the operator may also preempt the AI while it is processing.
    ("NEW", TicketTrigger.OPERATOR_REPLY, "PENDING_USER"),
    ("AI_PROCESSING", TicketTrigger.OPERATOR_REPLY, "PENDING_USER"),
    ("OPEN", TicketTrigger.OPERATOR_REPLY, "PENDING_USER"),
    ("PENDING_USER", TicketTrigger.OPERATOR_REPLY, "PENDING_USER"),
    # Operator resolve (docs/01 §3) — including an AI-processing ticket.
    ("NEW", TicketTrigger.OPERATOR_RESOLVED, "RESOLVED"),
    ("AI_PROCESSING", TicketTrigger.OPERATOR_RESOLVED, "RESOLVED"),
    ("OPEN", TicketTrigger.OPERATOR_RESOLVED, "RESOLVED"),
    ("PENDING_USER", TicketTrigger.OPERATOR_RESOLVED, "RESOLVED"),
    # Operator close: decides himself, no auto-close (docs/01 §3).
    ("NEW", TicketTrigger.OPERATOR_CLOSED, "CLOSED"),
    ("AI_PROCESSING", TicketTrigger.OPERATOR_CLOSED, "CLOSED"),
    ("OPEN", TicketTrigger.OPERATOR_CLOSED, "CLOSED"),
    ("PENDING_USER", TicketTrigger.OPERATOR_CLOSED, "CLOSED"),
    ("RESOLVED", TicketTrigger.OPERATOR_CLOSED, "CLOSED"),
    # Gateway trigger codes (D-043 §7): only from AI_PROCESSING - the code
    # arrives in the gateway's answer while the dialog is being processed.
    ("AI_PROCESSING", TicketTrigger.AI_RESOLVED, "RESOLVED"),
    ("AI_PROCESSING", TicketTrigger.AI_REQUESTED_HANDOFF, "OPEN"),
]

FORBIDDEN_TICKET = [
    # D-039: no direct user message target for CLOSED and RESOLVED (D-010
    # revised: both start a new ticket via routing P-04) and AI cannot
    # answer fresh tickets (nobody asked yet).
    ("CLOSED", TicketTrigger.USER_MESSAGE),
    ("RESOLVED", TicketTrigger.USER_MESSAGE),
    ("NEW", TicketTrigger.AI_REPLY),
    # AI never answers human-mode, resolved or closed tickets.
    ("PENDING_USER", TicketTrigger.AI_REPLY),
    ("RESOLVED", TicketTrigger.AI_REPLY),
    ("CLOSED", TicketTrigger.AI_REPLY),
    # Trigger codes only fire while the gateway processes the dialog (D-043):
    # not on fresh/human/resolved/closed tickets.
    ("NEW", TicketTrigger.AI_RESOLVED),
    ("OPEN", TicketTrigger.AI_RESOLVED),
    ("PENDING_USER", TicketTrigger.AI_RESOLVED),
    ("RESOLVED", TicketTrigger.AI_RESOLVED),
    ("CLOSED", TicketTrigger.AI_RESOLVED),
    ("NEW", TicketTrigger.AI_REQUESTED_HANDOFF),
    ("OPEN", TicketTrigger.AI_REQUESTED_HANDOFF),
    ("PENDING_USER", TicketTrigger.AI_REQUESTED_HANDOFF),
    ("RESOLVED", TicketTrigger.AI_REQUESTED_HANDOFF),
    ("CLOSED", TicketTrigger.AI_REQUESTED_HANDOFF),
    # Resolve is not repeatable; a resolved ticket is terminal (D-010
    # revised): no replies after RESOLVED, close/resolve/replies impossible
    # after CLOSED.
    ("RESOLVED", TicketTrigger.OPERATOR_RESOLVED),
    ("RESOLVED", TicketTrigger.OPERATOR_REPLY),
    ("CLOSED", TicketTrigger.OPERATOR_RESOLVED),
    ("CLOSED", TicketTrigger.OPERATOR_REPLY),
    ("CLOSED", TicketTrigger.OPERATOR_CLOSED),
]

ALLOWED_DIALOG = [
    ("AI_ACTIVE", DialogTrigger.HUMAN_HANDOFF, "HUMAN_PENDING"),
    ("AI_ACTIVE", DialogTrigger.OPERATOR_TOOK_OVER, "HUMAN_ACTIVE"),
    ("AI_ACTIVE", DialogTrigger.CONVERSATION_CLOSED, "CLOSED"),
    ("HUMAN_PENDING", DialogTrigger.OPERATOR_TOOK_OVER, "HUMAN_ACTIVE"),
    ("HUMAN_PENDING", DialogTrigger.CONVERSATION_CLOSED, "CLOSED"),
    ("HUMAN_ACTIVE", DialogTrigger.CONVERSATION_CLOSED, "CLOSED"),
]

FORBIDDEN_DIALOG = [
    # No return to AI after Handoff (D-014); no handoff request in human modes.
    ("HUMAN_ACTIVE", DialogTrigger.HUMAN_HANDOFF),
    ("HUMAN_PENDING", DialogTrigger.HUMAN_HANDOFF),
    ("HUMAN_ACTIVE", DialogTrigger.OPERATOR_TOOK_OVER),
    ("CLOSED", DialogTrigger.HUMAN_HANDOFF),
    ("CLOSED", DialogTrigger.OPERATOR_TOOK_OVER),
    ("CLOSED", DialogTrigger.CONVERSATION_CLOSED),
]

ALLOWED_SESSION = [
    ("ACTIVE", SessionTrigger.EXPIRED, "EXPIRED"),
    ("ACTIVE", SessionTrigger.ENDED, "ENDED"),
]

FORBIDDEN_SESSION = [
    ("EXPIRED", SessionTrigger.EXPIRED),
    ("EXPIRED", SessionTrigger.ENDED),
    ("ENDED", SessionTrigger.EXPIRED),
    ("ENDED", SessionTrigger.ENDED),
]


@pytest.mark.parametrize(
    ("current", "trigger", "expected", "dialog_mode"),
    [(case[0], case[1], case[2], case[3] if len(case) > 3 else None) for case in ALLOWED_TICKET],
)
def test_ticket_allowed(
    current: str,
    trigger: TicketTrigger,
    expected: str,
    dialog_mode: str | None,
) -> None:
    assert next_ticket_status(current, trigger, dialog_mode) == expected


@pytest.mark.parametrize(("current", "trigger"), FORBIDDEN_TICKET)
def test_ticket_forbidden(current: str, trigger: TicketTrigger) -> None:
    with pytest.raises(TransitionNotAllowed):
        next_ticket_status(current, trigger)


@pytest.mark.parametrize(("current", "trigger", "expected"), ALLOWED_DIALOG)
def test_dialog_allowed(current: str, trigger: DialogTrigger, expected: str) -> None:
    assert next_dialog_mode(current, trigger) == expected


@pytest.mark.parametrize(("current", "trigger"), FORBIDDEN_DIALOG)
def test_dialog_forbidden(current: str, trigger: DialogTrigger) -> None:
    with pytest.raises(TransitionNotAllowed):
        next_dialog_mode(current, trigger)


@pytest.mark.parametrize(("current", "trigger", "expected"), ALLOWED_SESSION)
def test_session_allowed(current: str, trigger: SessionTrigger, expected: str) -> None:
    assert next_session_status(current, trigger) == expected


@pytest.mark.parametrize(("current", "trigger"), FORBIDDEN_SESSION)
def test_session_forbidden(current: str, trigger: SessionTrigger) -> None:
    with pytest.raises(TransitionNotAllowed):
        next_session_status(current, trigger)
