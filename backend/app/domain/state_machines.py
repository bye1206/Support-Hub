"""Finite state machines for ticket, dialog and session lifecycles.

Pure domain rules, no DB access (docs/03 §4: transition checks live in the
domain service; DB CHECKs do not replace the FSM).

Sources:
- docs/01 §3 (confirmed ticket transitions),
- docs/01 §4 (dialog modes / Human Handoff),
- D-009/D-010/D-011/D-014,
- D-039 (owner): ticket status "Обработка ИИ" (AI_PROCESSING) — a user's
  message in the AI dialog puts the ticket into AI_PROCESSING, the AI
  answer completes processing. Per-transition details PROPOSED until the
  stage-4 report is confirmed by the owner.
"""

from enum import StrEnum

from app.domain.exceptions import TransitionNotAllowed


class TicketTrigger(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    AI_REPLY = "AI_REPLY"
    OPERATOR_REPLY = "OPERATOR_REPLY"
    OPERATOR_RESOLVED = "OPERATOR_RESOLVED"
    OPERATOR_CLOSED = "OPERATOR_CLOSED"


# Target status per trigger. A user message (USER_MESSAGE) never uses this
# dict: its target is source-dependent (_TICKET_USER_MESSAGE_TARGET).
_TICKET_TARGET: dict[TicketTrigger, str] = {
    TicketTrigger.AI_REPLY: "OPEN",
    TicketTrigger.OPERATOR_REPLY: "PENDING_USER",
    TicketTrigger.OPERATOR_RESOLVED: "RESOLVED",
    TicketTrigger.OPERATOR_CLOSED: "CLOSED",
}

# The user's message target depends on the current status (D-039):
# - an AI-mode ticket (NEW/OPEN, or already AI_PROCESSING) goes to
#   AI_PROCESSING — the message awaits the AI answer;
# - in human mode (PENDING_USER) the user answers the operator -> OPEN;
# - a message on a RESOLVED ticket reopens it into AI_PROCESSING, the
#   answer goes to AI again.
_TICKET_USER_MESSAGE_TARGET: dict[str, str] = {
    "NEW": "AI_PROCESSING",
    "AI_PROCESSING": "AI_PROCESSING",
    "OPEN": "AI_PROCESSING",
    "PENDING_USER": "OPEN",
    "RESOLVED": "AI_PROCESSING",
}

# From which ticket statuses each trigger is accepted. CLOSED is terminal for
# every trigger; a message after CLOSED creates a new ticket (routing, P-04).
_TICKET_ALLOWED_SOURCES: dict[TicketTrigger, frozenset[str]] = {
    TicketTrigger.USER_MESSAGE: frozenset(_TICKET_USER_MESSAGE_TARGET),
    # An AI reply is only possible in the AI dialog: the ticket is either
    # already processing or open awaiting the user's next move. AI never
    # answers NEW (nobody asked yet) / human-mode / resolved tickets.
    TicketTrigger.AI_REPLY: frozenset({"AI_PROCESSING", "OPEN"}),
    # Operator reply straight to PENDING_USER (D-011); the operator may also
    # preempt the AI while it is processing. Answering a RESOLVED ticket
    # means work continues — same target.
    TicketTrigger.OPERATOR_REPLY: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER", "RESOLVED"}
    ),
    TicketTrigger.OPERATOR_RESOLVED: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER"}
    ),
    # The operator decides when to close (docs/01 §3); no auto-close exists.
    TicketTrigger.OPERATOR_CLOSED: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER", "RESOLVED"}
    ),
}


def next_ticket_status(current: str, trigger: TicketTrigger) -> str:
    """Return the ticket status after the trigger; raises when forbidden."""
    if trigger is TicketTrigger.USER_MESSAGE:
        target = _TICKET_USER_MESSAGE_TARGET.get(current)
        if target is None:
            raise TransitionNotAllowed("ticket", current, trigger.value)
        return target
    target = _TICKET_TARGET[trigger]
    if current in _TICKET_ALLOWED_SOURCES[trigger]:
        return str(target)
    raise TransitionNotAllowed("ticket", current, str(target))


class DialogTrigger(StrEnum):
    HUMAN_HANDOFF = "HUMAN_HANDOFF"  # AI requested handoff (stage 6)
    OPERATOR_TOOK_OVER = "OPERATOR_TOOK_OVER"  # claim or first operator reply
    CONVERSATION_CLOSED = "CONVERSATION_CLOSED"


_DIALOG_ALLOWED: dict[str, frozenset[str]] = {
    "AI_ACTIVE": frozenset({"HUMAN_PENDING", "HUMAN_ACTIVE", "CLOSED"}),
    "HUMAN_PENDING": frozenset({"HUMAN_ACTIVE", "CLOSED"}),
    # After Handoff there is no return to AI (D-014).
    "HUMAN_ACTIVE": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}

_DIALOG_TARGET: dict[DialogTrigger, str] = {
    DialogTrigger.HUMAN_HANDOFF: "HUMAN_PENDING",
    DialogTrigger.OPERATOR_TOOK_OVER: "HUMAN_ACTIVE",
    DialogTrigger.CONVERSATION_CLOSED: "CLOSED",
}


def next_dialog_mode(current: str, trigger: DialogTrigger) -> str:
    target = _DIALOG_TARGET[trigger]
    if target in _DIALOG_ALLOWED[current]:
        return target
    raise TransitionNotAllowed("conversation", current, target)


class SessionTrigger(StrEnum):
    EXPIRED = "EXPIRED"  # worker or lazy read marks it
    ENDED = "ENDED"  # explicit end (e.g. conversation closed)


_SESSION_ALLOWED: dict[str, frozenset[str]] = {
    "ACTIVE": frozenset({"EXPIRED", "ENDED"}),
    "EXPIRED": frozenset(),
    "ENDED": frozenset(),
}

_SESSION_TARGET: dict[SessionTrigger, str] = {
    SessionTrigger.EXPIRED: "EXPIRED",
    SessionTrigger.ENDED: "ENDED",
}


def next_session_status(current: str, trigger: SessionTrigger) -> str:
    target = _SESSION_TARGET[trigger]
    if target in _SESSION_ALLOWED[current]:
        return target
    raise TransitionNotAllowed("session", current, target)
