"""Operator API (stage 7, pass 1): queue, ticket card, replies, statuses,
assignment, handoff acceptance.

Auth (P-22 PROPOSED, docs/08 §1): dev bearer token + email header until
Keycloak parameters arrive (Q-09); pass 2 swaps the authentication internals
only. Every endpoint resolves the active Operator and audits actions via the
services (actor=OPERATOR). No business logic here (AGENTS.md §6).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.auth.operators import require_operator
from app.errors import ApiError
from app.models import Message, Operator, Ticket, TicketStatus
from app.repositories.messages import MessageRepository
from app.repositories.tickets import TicketRepository
from app.services.messages import MessageService
from app.services.tickets import TicketService

router = APIRouter(prefix="/api/v1/operator", tags=["operator"])


def _ticket_view(ticket: Ticket, *, user_email: str | None = None) -> dict[str, Any]:
    return {
        "ticket_id": str(ticket.id),
        "conversation_id": str(ticket.conversation_id),
        "user_id": str(ticket.user_id),
        "status": str(ticket.status),
        "priority": ticket.priority,
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }


def _message_view(message: Message) -> dict[str, Any]:
    return {
        "message_id": str(message.id),
        "sequence_no": message.sequence_no,
        "author_type": str(message.author_type),
        "text": message.text,
        "created_at": message.created_at.isoformat(),
    }


def _map_value_error(exc: ValueError) -> ApiError:
    text = str(exc)
    if "not found" in text.lower():
        return ApiError(code="NOT_FOUND", message=text, status_code=404)
    return ApiError(code="STATE_CONFLICT", message=text, status_code=409)


@router.get("/tickets")
async def list_tickets(
    request: Request,
    operator: Annotated[Operator, Depends(require_operator)],
    status: TicketStatus | None = None,
    assignee: str | None = Query(default=None, description="operator id, 'me' or 'unassigned'"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Operator queue: newest activity first (docs/06 §2)."""
    assignee_id: uuid.UUID | None = None
    unassigned_only = False
    if assignee == "me":
        assignee_id = operator.id
    elif assignee == "unassigned":
        unassigned_only = True
    elif assignee is not None:
        try:
            assignee_id = uuid.UUID(assignee)
        except ValueError as exc:
            raise ApiError(
                code="VALIDATION_ERROR", message="Bad assignee filter", status_code=422
            ) from exc

    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        tickets = await TicketRepository().list_filtered(
            session,
            status=status,
            assignee_id=assignee_id,
            unassigned_only=unassigned_only,
            limit=limit,
            offset=offset,
        )
    return {"tickets": [_ticket_view(t) for t in tickets], "limit": limit, "offset": offset}


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Ticket card: ticket + FULL message history (D-015, docs/06 §3)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        messages = await MessageRepository().list_for_conversation(
            session, ticket.conversation_id
        )
    return {
        **_ticket_view(ticket),
        "messages": [_message_view(m) for m in messages],
    }


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("/tickets/{ticket_id}/replies")
async def reply_to_ticket(
    ticket_id: uuid.UUID,
    payload: ReplyIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Public reply (docs/06 §4): message + PENDING_USER + outbox, one tx."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            result = await MessageService().add_operator_reply(
                session,
                ticket_id=ticket_id,
                text=payload.text,
                operator_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {
        "message_id": str(result.message.id),
        "ticket_id": str(result.ticket.id),
        "status": str(result.ticket.status),
    }


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket = await TicketService().resolve(
                session, ticket_id, actor_id=operator.id
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"ticket_id": str(ticket.id), "status": str(ticket.status)}


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket = await TicketService().close(session, ticket_id, actor_id=operator.id)
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"ticket_id": str(ticket.id), "status": str(ticket.status)}


class AssignIn(BaseModel):
    # null = unassign; a deactivated operator is rejected by the service.
    assignee_id: uuid.UUID | None = None


@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: AssignIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Manual assignment (docs/06 §6); auto-assignment stays behind a flag."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket = await TicketService().assign(
                session,
                ticket_id,
                assignee_id=payload.assignee_id,
                actor_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {
        "ticket_id": str(ticket.id),
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
    }


@router.post("/conversations/{conversation_id}/handoff/accept")
async def accept_handoff(
    conversation_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Claim the dialog offered by AI (D-014): HUMAN_PENDING -> HUMAN_ACTIVE."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            await TicketService().accept_handoff(
                session, conversation_id, actor_id=operator.id
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"conversation_id": str(conversation_id), "mode": "HUMAN_ACTIVE"}
