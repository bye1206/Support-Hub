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
- D-010 revised (owner, stage 9 round 4): a RESOLVED ticket is terminal —
  the user's next message starts a NEW ticket; no reopen exists.
- Owner (stage 9 round 4): after the human handoff the AI no longer
  processes user messages — in a human dialog (HUMAN_ACTIVE/HUMAN_PENDING)
  any user message targets OPEN ("В работе").
"""

from enum import StrEnum

from app.domain.exceptions import TransitionNotAllowed


class TicketTrigger(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    AI_REPLY = "AI_REPLY"
    OPERATOR_REPLY = "OPERATOR_REPLY"
    OPERATOR_RESOLVED = "OPERATOR_RESOLVED"
    OPERATOR_CLOSED = "OPERATOR_CLOSED"
    # D-043 (gateway trigger codes): the user's magic word confirmed the
    # problem is solved / asked for a human. AI acts, no message is published.
    AI_RESOLVED = "AI_RESOLVED"
    AI_REQUESTED_HANDOFF = "AI_REQUESTED_HANDOFF"


# Target status per trigger. A user message (USER_MESSAGE) never uses this
# dict: its target is source-dependent (_TICKET_USER_MESSAGE_TARGET).
_TICKET_TARGET: dict[TicketTrigger, str] = {
    TicketTrigger.AI_REPLY: "OPEN",
    TicketTrigger.OPERATOR_REPLY: "PENDING_USER",
    TicketTrigger.OPERATOR_RESOLVED: "RESOLVED",
    TicketTrigger.OPERATOR_CLOSED: "CLOSED",
    # Gateway trigger codes (D-043): user confirmed solved / asked for human.
    TicketTrigger.AI_RESOLVED: "RESOLVED",
    TicketTrigger.AI_REQUESTED_HANDOFF: "OPEN",
}

# The user's message target depends on the current status and the dialog
# mode (D-039, stage 9 round 4):
# - AI dialog (AI_ACTIVE): the message awaits the AI answer ->
#   AI_PROCESSING ("Обработка ИИ"), the answer completes processing;
# - human dialog (HUMAN_ACTIVE / HUMAN_PENDING): the AI is out of the loop,
#   any user message targets OPEN ("В работе");
# - a message on a RESOLVED ticket never reaches the FSM: routing starts a
#   new ticket (D-010 revised).
_TICKET_USER_MESSAGE_TARGET: dict[str, str] = {
    "NEW": "AI_PROCESSING",
    "AI_PROCESSING": "AI_PROCESSING",
    "OPEN": "AI_PROCESSING",
    "PENDING_USER": "OPEN",
}
_TICKET_USER_MESSAGE_TARGET_HUMAN: dict[str, str] = {
    "NEW": "OPEN",
    "AI_PROCESSING": "OPEN",
    "OPEN": "OPEN",
    "PENDING_USER": "OPEN",
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
    # preempt the AI while it is processing. RESOLVED is terminal (D-010
    # revised): no further replies, the user starts a new ticket instead.
    TicketTrigger.OPERATOR_REPLY: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER"}
    ),
    TicketTrigger.OPERATOR_RESOLVED: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER"}
    ),
    # The operator decides when to close (docs/01 §3); no auto-close exists.
    TicketTrigger.OPERATOR_CLOSED: frozenset(
        {"NEW", "AI_PROCESSING", "OPEN", "PENDING_USER", "RESOLVED"}
    ),
    # Trigger codes arrive while the gateway is processing this dialog.
    TicketTrigger.AI_RESOLVED: frozenset({"AI_PROCESSING"}),
    TicketTrigger.AI_REQUESTED_HANDOFF: frozenset({"AI_PROCESSING"}),
}


def next_ticket_status(
    current: str,
    trigger: TicketTrigger,
    dialog_mode: str | None = None,
) -> str:
    """Return the ticket status after the trigger; raises when forbidden.

    For USER_MESSAGE the dialog mode selects the target map: in a human
    dialog (HUMAN_ACTIVE / HUMAN_PENDING) user messages always go to OPEN.
    """
    if trigger is TicketTrigger.USER_MESSAGE:
        targets = (
            _TICKET_USER_MESSAGE_TARGET_HUMAN
            if dialog_mode in {"HUMAN_ACTIVE", "HUMAN_PENDING"}
            else _TICKET_USER_MESSAGE_TARGET
        )
        target = targets.get(current)
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
