"""Operator API (stage 7, pass 1): queue, ticket card, replies, statuses,
assignment, handoff acceptance.

Auth (P-22 PROPOSED, docs/08 §1): dev bearer token + email header until
Keycloak parameters arrive (Q-09); pass 2 swaps the authentication internals
only. Every endpoint resolves the active Operator and audits actions via the
services (actor=OPERATOR). No business logic here (AGENTS.md §6).
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select

from app.auth.operators import require_operator
from app.errors import ApiError
from app.integrations.ad_directory import AdUnavailableError
from app.models import (
    AuditLog,
    ConversationSession,
    InternalNote,
    Message,
    Operator,
    SessionStatus,
    Tag,
    Ticket,
    TicketStatus,
)
from app.repositories.categories import TicketCategoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.operators import OperatorRepository
from app.repositories.tags import TagRepository
from app.repositories.tickets import TicketRepository
from app.services.ad_info import AdInfoService
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


@router.get("/me/photo")
async def get_current_operator_photo(
    operator: Annotated[Operator, Depends(require_operator)],
) -> Response:
    """The operator's own AD photo (avatar in the session footer)."""
    service = AdInfoService()
    photo = await service.photo_for_login(operator.email)
    if photo is None and "@" in operator.email:
        photo = await service.photo_for_login(operator.email.split("@", 1)[0])
    if photo is None:
        raise ApiError(code="NOT_FOUND", message="Фото не найдено", status_code=404)
    media = "image/png" if photo[:4] == b"\x89PN" else "image/jpeg"
    return Response(content=photo, media_type=media)


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
        "pending_assignee_id": (
            str(ticket.pending_assignee_id) if ticket.pending_assignee_id else None
        ),
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


async def _notify_workspace(request: Request) -> None:
    """Nudge open workspaces to resync (best effort; never fails a request)."""
    try:
        await request.app.state.deps.redis.publish_event(
            json.dumps({"type": "tickets.changed"})
        )
    except Exception:  # noqa: BLE001 - redis trouble must not break the API
        pass


@router.get("/tickets")
async def list_tickets(
    request: Request,
    operator: Annotated[Operator, Depends(require_operator)],
    status: TicketStatus | None = None,
    assignee: str | None = Query(default=None, description="operator id, 'me' or 'unassigned'"),
    category: str | None = Query(default=None, description="category id"),
    tag: str | None = Query(default=None, description="tag name, case-insensitive"),
    created_from: Annotated[datetime | None, Query(description="ISO date/time from")] = None,
    created_to: Annotated[datetime | None, Query(description="ISO date/time to")] = None,
    user: Annotated[
        str | None, Query(description="user UUID, login or name fragment")
    ] = None,
    q: Annotated[
        str | None, Query(description="ticket UUID or short-id prefix")
    ] = None,
    text: Annotated[
        str | None, Query(description="substring of any message in the chat")
    ] = None,
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
            created_from=created_from,
            created_to=created_to,
            user_query=user,
            ticket_query=q,
            text_query=text,
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
        active_session = await session.scalar(
            select(ConversationSession)
            .where(
                ConversationSession.conversation_id == ticket.conversation_id,
                ConversationSession.status == SessionStatus.ACTIVE,
            )
            .limit(1)
        )
    return {
        **_ticket_view(ticket, tags=tags),
        "messages": [_message_view(m) for m in messages],
        "session": (
            {
                "started_at": active_session.started_at.isoformat(),
                "expires_at": active_session.expires_at.isoformat(),
            }
            if active_session
            else None
        ),
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
    await _notify_workspace(request)
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
    await _notify_workspace(request)
    return {"ticket_id": str(ticket.id), "status": str(ticket.status)}


class AssignIn(BaseModel):
    # null = unassign; a deactivated operator is rejected by the service.
    assignee_id: uuid.UUID | None = None


class PriorityIn(BaseModel):
    priority: str = Field(pattern="^(NORMAL|HIGH|URGENT)$")


@router.patch("/tickets/{ticket_id}/priority")
async def set_ticket_priority(
    ticket_id: uuid.UUID,
    payload: PriorityIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Change the priority (docs/03 #16); any operator may escalate."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket = await TicketService().set_priority(
                session,
                ticket_id,
                priority=payload.priority,
                actor_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return {"ticket_id": str(ticket.id), "priority": ticket.priority}



@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: AssignIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Manual assignment (docs/06 §6); auto-assignment stays behind a flag.
    Capacity-full target: the ticket is queued and lands on the operator when
    a slot frees up (deferred=true)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            ticket, deferred = await TicketService().assign(
                session,
                ticket_id,
                assignee_id=payload.assignee_id,
                actor_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    await _notify_workspace(request)
    return {
        "ticket_id": str(ticket.id),
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "pending_assignee_id": (
            str(ticket.pending_assignee_id) if ticket.pending_assignee_id else None
        ),
        "deferred": deferred,
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
                "is_active": category.is_active,
            }
            for category in categories
        ]
    }


@router.get("/colleagues")
async def list_colleagues(
    operator: Annotated[Operator, Depends(require_operator)], request: Request
) -> dict[str, Any]:
    """Active staff for ticket transfer selection (docs/06 §6)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        colleagues = await OperatorRepository().list_active(session)
    return {
        "colleagues": [
            {
                "operator_id": str(colleague.id),
                "display_name": colleague.display_name,
                "email": colleague.email,
                "presence_status": colleague.presence_status.value,
            }
            for colleague in colleagues
            if colleague.id != operator.id
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


@router.get("/users/{user_id}/ad-info")
async def user_ad_info(
    user_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Employee card from AD (P-29): org data, groups, password dates.

    Degrades to ``{"available": false}`` when AD is unreachable or no service
    account is configured; never blocks the ticket view."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            return await AdInfoService().get_for_user(session, user_id)
        except LookupError as exc:
            raise ApiError(code="NOT_FOUND", message=str(exc), status_code=404) from exc


@router.get("/users/{user_id}/ad-photo")
async def user_ad_photo(
    user_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> Response:
    """Cached AD photo bytes (thumbnailPhoto); 404 when none is known."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            photo = await AdInfoService().get_photo(session, user_id)
        except LookupError as exc:
            raise ApiError(code="NOT_FOUND", message=str(exc), status_code=404) from exc
    if not photo:
        raise ApiError(code="NOT_FOUND", message="No AD photo", status_code=404)
    media_type = "image/png" if photo.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=photo, media_type=media_type)


class AdSearchOut(BaseModel):
    login: str = ""
    full_name: str = ""
    email: str = ""
    title: str = ""
    department: str = ""
    company: str = ""
    phone: str = ""
    disabled: bool = False
    groups: list[str] = []
    mobile: str = ""
    manager: str = ""
    password_changed_at: str | None = None
    password_expires_at: str | None = None
    locked: bool = False
    demo: bool = False


def _normalize_ad_card(card: dict[str, Any]) -> AdSearchOut:
    changed = card.get("password_changed_at")
    expires = card.get("password_expires_at")
    return AdSearchOut(
        login=str(card.get("login") or ""),
        full_name=str(card.get("full_name") or ""),
        email=str(card.get("email") or ""),
        title=str(card.get("title") or ""),
        department=str(card.get("department") or ""),
        company=str(card.get("company") or ""),
        phone=str(card.get("phone") or ""),
        mobile=str(card.get("mobile") or ""),
        manager=str(card.get("manager") or ""),
        disabled=bool(card.get("disabled")),
        locked=bool(card.get("locked")),
        groups=[str(g) for g in card.get("groups") or []],
        password_changed_at=str(changed) if changed else None,
        password_expires_at=str(expires) if expires else None,
        demo=bool(card.get("demo")),
    )


@router.get("/ad/search")
async def ad_search(
    operator: Annotated[Operator, Depends(require_operator)],
    q: Annotated[str, Query(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """AD people search for the lookup dialog (login / name / e-mail)."""
    try:
        results = await AdInfoService().search(q, limit=limit)
    except AdUnavailableError as exc:
        raise ApiError(
            code="AD_UNAVAILABLE", message="AD недоступен, попробуйте позже", status_code=503
        ) from exc
    return {"results": [_normalize_ad_card(card).model_dump() for card in results]}


@router.get("/ad/user")
async def ad_user(
    operator: Annotated[Operator, Depends(require_operator)],
    login: Annotated[str, Query(min_length=1, max_length=128)],
) -> dict[str, Any]:
    """Full AD card for one login (detail view of the lookup dialog)."""
    try:
        card = await AdInfoService().user_by_login(login)
    except AdUnavailableError as exc:
        raise ApiError(
            code="AD_UNAVAILABLE", message="AD недоступен, попробуйте позже", status_code=503
        ) from exc
    if card is None:
        raise ApiError(
            code="NOT_FOUND", message="Пользователь не найден в AD", status_code=404
        )
    return _normalize_ad_card(card).model_dump()


@router.get("/tickets/{ticket_id}/assignment-history")
async def ticket_assignment_history(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Movement history: operator assignments, deferred queueing and the
    AI -> operator handoff, without exposing unrelated audit records."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        stmt = (
            select(AuditLog)
            .where(
                or_(
                    and_(
                        AuditLog.entity_type == "ticket",
                        AuditLog.entity_id == ticket_id,
                        AuditLog.action.in_(
                            ("ticket.assigned", "ticket.assignment_queued")
                        ),
                    ),
                    and_(
                        AuditLog.entity_type == "conversation",
                        AuditLog.entity_id == ticket.conversation_id,
                        AuditLog.action == "handoff.accepted",
                    ),
                )
            )
            .order_by(desc(AuditLog.created_at))
        )
        events = list((await session.scalars(stmt)).all())
    return {
        "events": [
            {
                "action": event.action,
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
