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
from sqlalchemy import desc, select

from app.auth.operators import require_operator
from app.errors import ApiError
from app.models import (
    AuditLog,
    InternalNote,
    Message,
    Operator,
    Tag,
    Ticket,
    TicketStatus,
)
from app.repositories.categories import TicketCategoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.tags import TagRepository
from app.repositories.tickets import TicketRepository
from app.services.messages import MessageService
from app.services.notes import NoteService
from app.services.tickets import TicketService

router = APIRouter(prefix="/api/v1/operator", tags=["operator"])


@router.get("/me")
async def get_current_operator(
    operator: Annotated[Operator, Depends(require_operator)],
) -> dict[str, str]:
    """Return the authenticated operator profile for workspace actions."""
    return {
        "operator_id": str(operator.id),
        "email": operator.email,
        "display_name": operator.display_name or operator.email,
        "role": str(operator.role),
    }


def _ticket_view(
    ticket: Ticket, *, tags: list[Tag] | None = None
) -> dict[str, Any]:
    return {
        "ticket_id": str(ticket.id),
        "conversation_id": str(ticket.conversation_id),
        "user_id": str(ticket.user_id),
        "status": str(ticket.status),
        "priority": ticket.priority,
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "category_id": str(ticket.category_id) if ticket.category_id else None,
        "tags": [t.name for t in (tags or [])],
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }


def _note_view(note: InternalNote) -> dict[str, Any]:
    return {
        "note_id": str(note.id),
        "conversation_id": str(note.conversation_id),
        "author_id": str(note.author_id),
        "body": note.body,
        "created_at": note.created_at.isoformat(),
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
    category: str | None = Query(default=None, description="category id"),
    tag: str | None = Query(default=None, description="tag name, case-insensitive"),
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
    category_id: uuid.UUID | None = None
    if category is not None:
        try:
            category_id = uuid.UUID(category)
        except ValueError as exc:
            raise ApiError(
                code="VALIDATION_ERROR", message="Bad category filter", status_code=422
            ) from exc

    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        tickets = await TicketRepository().list_filtered(
            session,
            status=status,
            assignee_id=assignee_id,
            unassigned_only=unassigned_only,
            category_id=category_id,
            tag_name=tag,
            limit=limit,
            offset=offset,
        )
        tag_map = await TagRepository().map_for_tickets(
            session, [t.id for t in tickets]
        )
    return {
        "tickets": [
            _ticket_view(t, tags=tag_map.get(t.id, [])) for t in tickets
        ],
        "limit": limit,
        "offset": offset,
    }


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
        tags = await TicketService().list_tags(session, ticket_id)
    return {
        **_ticket_view(ticket, tags=tags),
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


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


@router.post("/conversations/{conversation_id}/notes", status_code=201)
async def create_note(
    conversation_id: uuid.UUID,
    payload: NoteIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Internal note (D-025): not a message, no status change, no outbox."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            note = await NoteService().create(
                session,
                conversation_id=conversation_id,
                author_id=operator.id,
                body=payload.body,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return _note_view(note)


@router.get("/conversations/{conversation_id}/notes")
async def list_notes(
    conversation_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            notes = await NoteService().list(session, conversation_id)
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"notes": [_note_view(n) for n in notes]}


@router.get("/categories")
async def list_categories(
    operator: Annotated[Operator, Depends(require_operator)], request: Request
) -> dict[str, Any]:
    """Read-only category directory; category management is stage 9."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        categories = await TicketCategoryRepository().list(session)
    return {
        "categories": [
            {
                "category_id": str(category.id),
                "name": category.name,
                "parent_id": str(category.parent_id) if category.parent_id else None,
            }
            for category in categories
        ]
    }


@router.get("/users/{user_id}/tickets")
async def list_user_tickets(
    user_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Previous requests for the customer card (docs/06 §5)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        tickets = await TicketRepository().list_for_user(session, user_id, limit=limit)
        tag_map = await TagRepository().map_for_tickets(
            session, [ticket.id for ticket in tickets]
        )
    return {
        "tickets": [
            _ticket_view(ticket, tags=tag_map.get(ticket.id, [])) for ticket in tickets
        ]
    }


@router.get("/tickets/{ticket_id}/assignment-history")
async def ticket_assignment_history(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Read assignment audit events without exposing unrelated audit records."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == "ticket",
                AuditLog.entity_id == ticket_id,
                AuditLog.action == "ticket.assigned",
            )
            .order_by(desc(AuditLog.created_at))
        )
        events = list((await session.scalars(stmt)).all())
    return {
        "events": [
            {
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "assignee_id": (event.details or {}).get("assignee_id"),
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
    }


@router.get("/tickets/{ticket_id}/tag-details")
async def ticket_tag_details(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        if await TicketRepository().get(session, ticket_id) is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        tags = await TicketService().list_tags(session, ticket_id)
    return {
        "tags": [{"tag_id": str(tag.id), "name": tag.name} for tag in tags]
    }


class CategoryIn(BaseModel):
    # null = clear the category.
    category_id: uuid.UUID | None = None


@router.patch("/tickets/{ticket_id}/category")
async def set_ticket_category(
    ticket_id: uuid.UUID,
    payload: CategoryIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Set the main category (D-026); the directory itself is stage 9."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket = await TicketService().set_category(
                session,
                ticket_id,
                category_id=payload.category_id,
                actor_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {
        "ticket_id": str(ticket.id),
        "category_id": str(ticket.category_id) if ticket.category_id else None,
    }


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/tickets/{ticket_id}/tags")
async def add_ticket_tag(
    ticket_id: uuid.UUID,
    payload: TagIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Attach a tag by name (get_or_create, case-insensitive, P-23)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            tag = await TicketService().add_tag(
                session,
                ticket_id,
                tag_name=payload.name,
                actor_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"tag_id": str(tag.id), "name": tag.name}


@router.delete("/tickets/{ticket_id}/tags/{tag_id}", status_code=204)
async def remove_ticket_tag(
    ticket_id: uuid.UUID,
    tag_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> None:
    """Detach a tag; the tag row itself survives (P-23)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            await TicketService().remove_tag(
                session, ticket_id, tag_id=tag_id, actor_id=operator.id
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
