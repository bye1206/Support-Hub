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

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.operators import require_operator
from app.config import get_settings
from app.errors import ApiError
from app.infra.file_storage import FileStorageError, LocalFileStorage
from app.integrations.ad_directory import AdUnavailableError
from app.integrations.tag.direct import fetch_tag_avatar
from app.models import (
    AuditActorType,
    AuditLog,
    ConversationSession,
    InternalNote,
    Message,
    MessageAttachment,
    Operator,
    OperatorRole,
    SessionStatus,
    Tag,
    Ticket,
    TicketStatus,
    User,
)
from app.repositories.attachments import AttachmentRepository
from app.repositories.categories import TicketCategoryRepository
from app.repositories.kb import KbRepository
from app.repositories.messages import MessageRepository
from app.repositories.operators import OperatorRepository
from app.repositories.participants import ParticipantRepository
from app.repositories.ratings import TicketRatingRepository
from app.repositories.tags import TagRepository
from app.repositories.tickets import TicketRepository
from app.repositories.users import UserRepository
from app.services.ad_info import AdInfoService
from app.services.export import build_tickets_xlsx
from app.services.messages import MessageService
from app.services.notes import NoteService
from app.services.tickets import TicketService

router = APIRouter(prefix="/api/v1/operator", tags=["operator"])


@router.get("/me")
async def get_current_operator(
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, str | float | None]:
    """Return the authenticated operator profile for workspace actions."""
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        averages = await TicketRatingRepository().avg_by_operators(session, {operator.id})
    return {
        "operator_id": str(operator.id),
        "email": operator.email,
        "display_name": operator.display_name or operator.email,
        "role": str(operator.role),
        # Owner request (2026-11-20): the golden-crown rating in the footer.
        "avg_rating": (
            round(averages[operator.id], 2) if operator.id in averages else None
        ),
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
    ticket: Ticket,
    *,
    tags: list[Tag] | None = None,
    user_name: str | None = None,
    unread_from_user: int = 0,
    assignee_name: str | None = None,
    user_login: str | None = None,
    specialists: list[str] | None = None,
    is_specialist: bool = False,
) -> dict[str, Any]:
    return {
        "ticket_id": str(ticket.id),
        "conversation_id": str(ticket.conversation_id),
        "user_id": str(ticket.user_id),
        # Owner request (2026-11-17): the queue must show the person, not a
        # short UUID — display_name (Tag profile / AD), fallback frontend.
        "user_name": user_name,
        # Owner request (2026-11-20): the login for the history tables.
        "user_login": user_login,
        # Owner request (2026-11-18): user messages since the operator's
        # last reply — badge in the queue, resets on the operator's answer.
        "unread_from_user": unread_from_user,
        "status": str(ticket.status),
        "priority": ticket.priority,
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        # Owner (2026-11-19): the history shows the operator's name, not a UUID.
        "assignee_name": assignee_name,
        "pending_assignee_id": (
            str(ticket.pending_assignee_id) if ticket.pending_assignee_id else None
        ),
        "category_id": str(ticket.category_id) if ticket.category_id else None,
        "tags": [t.name for t in (tags or [])],
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        # Owner request (2026-11-19): the 15-minute reply SLA clock.
        "sla": {
            "deadline": (
                ticket.sla_deadline.isoformat() if ticket.sla_deadline else None
            ),
            "breached_at": (
                ticket.sla_breached_at.isoformat() if ticket.sla_breached_at else None
            ),
        },
        # Owner (2026-11-23, plan item 7): invited specialists (names for the
        # header) and whether the CURRENT operator is one of them.
        "specialists": specialists or [],
        "is_specialist": is_specialist,
    }


@router.get("/tickets/{ticket_id}/sla-history")
async def get_sla_history(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Status history + SLA events (owner request 2026-11-19); the workspace
    modal computes the per-status durations from these rows."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(
                code="NOT_FOUND", message="Ticket not found", status_code=404
            )
        events = await TicketRepository().list_history(session, ticket_id)
    return {
        "ticket_id": str(ticket_id),
        "events": [
            {
                "kind": str(event.kind),
                "from_status": event.from_status,
                "to_status": event.to_status,
                "changed_at": event.changed_at.isoformat(),
            }
            for event in events
        ],
    }


def _note_view(note: InternalNote, author_name: str | None = None) -> dict[str, Any]:
    return {
        "note_id": str(note.id),
        "conversation_id": str(note.conversation_id),
        "author_id": str(note.author_id),
        # Owner (2026-11-18): the timeline must show which operator wrote
        # the internal note.
        "author_name": author_name,
        "body": note.body,
        "created_at": note.created_at.isoformat(),
    }


def _message_view(
    message: Message,
    attachments: list[MessageAttachment] | None = None,
    author_name: str | None = None,
) -> dict[str, Any]:
    return {
        "message_id": str(message.id),
        "sequence_no": message.sequence_no,
        "author_type": str(message.author_type),
        # Owner (2026-11-19): the history shows WHO wrote the message (the
        # operator's name / the user's name), not just the role.
        "author_name": author_name,
        "text": message.text,
        "created_at": message.created_at.isoformat(),
        # Owner request (2026-11-19): files travel with the message.
        "attachments": [
            {
                "id": str(a.id),
                "file_name": a.file_name,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
            }
            for a in (attachments or [])
        ],
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


async def _user_name_map(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """id -> display name for the queue's person column (owner 2026-11-17).
    Prefers the AD full name ("Фамилия Имя Отчество" — gives proper
    "Фамилия И.О." initials in the UI); falls back to the Tag profile name."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(
            User.id,
            func.coalesce(
                User.ad_info["full_name"].astext, User.display_name
            ).label("person"),
        ).where(User.id.in_(user_ids))
    )
    return {row[0]: row[1] for row in rows}


async def _user_login_map(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """id -> LOGIN for the history/stats tables (owner request, 2026-11-20):
    the AD login when cached, else the Tag profile name."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.ad_info).where(User.id.in_(user_ids))
    )
    logins = {
        row[0]: ((row[1] or {}).get("login") or row[0])
        for row in rows
    }
    missing = [uid for uid in user_ids if isinstance(logins.get(uid), uuid.UUID)]
    if missing:
        from app.models import UserIdentity

        identity_rows = await session.execute(
            select(UserIdentity.user_id, UserIdentity.external_user_name).where(
                UserIdentity.user_id.in_(missing)
            )
        )
        names = {row[0]: row[1] for row in identity_rows if row[1]}
        logins.update(names)
    return {uid: str(login) for uid, login in logins.items()}


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
        user_names = await _user_name_map(session, [t.user_id for t in tickets])
        # Owner (2026-11-19): operator display names for the history.
        assignee_ids = {t.assignee_id for t in tickets if t.assignee_id}
        assignee_names: dict[Any, str] = {}
        if assignee_ids:
            rows = await session.scalars(
                select(Operator).where(Operator.id.in_(assignee_ids))
            )
            for op in rows:
                assignee_names[op.id] = op.display_name or op.email.split("@")[0]
        # Owner (2026-11-18): per-chat counter of user messages since the
        # operator's last reply (resets when the operator answers).
        unread = await MessageRepository().unread_counts(
            session, [t.conversation_id for t in tickets]
        )
        user_logins = await _user_login_map(session, [t.user_id for t in tickets])
        # Owner (2026-11-23, plan item 7): invited specialists per dialog.
        participant_map = await ParticipantRepository().active_operators(
            session, [t.conversation_id for t in tickets]
        )
    return {
        "tickets": [
            _ticket_view(
                t,
                tags=tag_map.get(t.id, []),
                user_name=user_names.get(t.user_id),
                unread_from_user=unread.get(t.conversation_id, 0),
                assignee_name=assignee_names.get(t.assignee_id),
                user_login=user_logins.get(t.user_id),
                specialists=[
                    operator.display_name or operator.email.split("@")[0]
                    for operator in participant_map.get(t.conversation_id, [])
                ],
                is_specialist=operator.id
                in {op.id for op in participant_map.get(t.conversation_id, [])},
            )
            for t in tickets
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/tickets/export.xlsx")
async def export_tickets_xlsx(
    request: Request,
    operator: Annotated[Operator, Depends(require_operator)],
    status: TicketStatus | None = None,
    assignee: str | None = Query(default=None, description="operator id, 'me' or 'unassigned'"),
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
    limit: int = Query(default=5000, ge=1, le=5000),
) -> Response:
    """Owner (2026-11-23, plan item 6): the history search results as .xlsx.

    Same filters as GET /tickets; the closed time comes from the ticket's
    status history (latest RESOLVED/CLOSED transition)."""
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
        content, filename, media_type = await build_tickets_xlsx(
            session,
            status=status,
            assignee_id=assignee_id,
            unassigned_only=unassigned_only,
            created_from=created_from,
            created_to=created_to,
            user_query=user,
            ticket_query=q,
            text_query=text,
            limit=limit,
        )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        attachments = await AttachmentRepository().for_conversation(
            session, ticket.conversation_id
        )
        attachments_by_message: dict[Any, list[MessageAttachment]] = {}
        for attachment in attachments:
            if attachment.message_id is not None:
                attachments_by_message.setdefault(attachment.message_id, []).append(
                    attachment
                )
        # Owner (2026-11-19): resolve message authors to display names —
        # the history shows the operator's / the user's real name.
        operator_ids = {m.author_operator_id for m in messages if m.author_operator_id}
        user_ids = {m.author_user_id for m in messages if m.author_user_id}
        name_by_operator: dict[Any, str] = {}
        name_by_user: dict[Any, str] = {}
        if operator_ids:
            rows = await session.scalars(
                select(Operator).where(Operator.id.in_(operator_ids))
            )
            for op in rows:
                name_by_operator[op.id] = op.display_name or op.email.split("@")[0]
        if user_ids:
            rows = await session.scalars(select(User).where(User.id.in_(user_ids)))
            for user in rows:
                name_by_user[user.id] = user.display_name or "Пользователь"
        tags = await TicketService().list_tags(session, ticket_id)
        active_session = await session.scalar(
            select(ConversationSession)
            .where(
                ConversationSession.conversation_id == ticket.conversation_id,
                ConversationSession.status == SessionStatus.ACTIVE,
            )
            .limit(1)
        )
        ticket_user = await session.get(User, ticket.user_id)
        assignee_name = None
        if ticket.assignee_id:
            assignee = await session.get(Operator, ticket.assignee_id)
            if assignee is not None:
                assignee_name = assignee.display_name or assignee.email.split("@")[0]
                assignee_email = assignee.email
            else:
                assignee_email = None
        else:
            assignee_email = None
        # Owner (2026-11-19): the history aside shows the person blocks —
        # user (FIO/login/email/manager) and operator (FIO/login/email).
        user_ad = (ticket_user.ad_info or {}) if ticket_user else {}
        participant_ops = await ParticipantRepository().active_operators(
            session, [ticket.conversation_id]
        )
        conv_participants = participant_ops.get(ticket.conversation_id, [])
    return {
        **_ticket_view(
            ticket,
            tags=tags,
            user_name=ticket_user.display_name if ticket_user else None,
            assignee_name=assignee_name,
            specialists=[
                operator.display_name or operator.email.split("@")[0]
                for operator in conv_participants
            ],
            is_specialist=operator.id in {op.id for op in conv_participants},
        ),
        "assignee_email": assignee_email,
        "user_ad": {
            "full_name": user_ad.get("full_name"),
            "login": user_ad.get("login"),
            "email": user_ad.get("email"),
            "manager": user_ad.get("manager"),
        },
        "messages": [
            _message_view(
                m,
                attachments_by_message.get(m.id),
                (
                    name_by_operator.get(m.author_operator_id)
                    if m.author_operator_id
                    else name_by_user.get(m.author_user_id)
                ),
            )
            for m in messages
        ],
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
    # Owner request (2026-11-19): a reply may carry only attachments, so the
    # text is optional when files are attached.
    text: str = Field(default="", max_length=10000)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)


def _content_disposition(file_name: str) -> str:
    """RFC 5987: file names are user text and may be non-ASCII (Cyrillic) —
    a raw header would fail latin-1 encoding and break the download."""
    from urllib.parse import quote

    ascii_fallback = file_name.encode("ascii", "ignore").decode() or "file"
    return (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(file_name)}"
    )


def _attachment_view(attachment: MessageAttachment) -> dict[str, Any]:
    return {
        "id": str(attachment.id),
        "file_name": attachment.file_name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
    }


@router.post("/tickets/{ticket_id}/attachments")
async def upload_ticket_attachment(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
    file: Annotated[UploadFile, File(...)],
) -> dict[str, Any]:
    """Composer upload (owner request 2026-11-19): store now, link on send."""
    content = await file.read()
    if not content:
        raise ApiError(
            code="EMPTY_FILE", message="Файл пустой", status_code=422
        )
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            attachment = await MessageService().add_operator_upload(
                session,
                ticket_id=ticket_id,
                file_name=file.filename or "file",
                mime_type=file.content_type or "application/octet-stream",
                content=content,
                operator_id=operator.id,
            )
        except ValueError as exc:
            raise _map_value_error(exc) from exc
    return _attachment_view(attachment)


@router.get("/attachments/{attachment_id}/file")
async def download_attachment(
    attachment_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> Response:
    """Stream one attachment's bytes (operator session required)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        attachment = await AttachmentRepository().get(session, attachment_id)
        if attachment is None:
            raise ApiError(
                code="NOT_FOUND", message="Вложение не найдено", status_code=404
            )
        storage_key, mime, file_name = (
            attachment.storage_key,
            attachment.mime_type,
            attachment.file_name,
        )
    try:
        content = await LocalFileStorage().open(storage_key)
    except FileStorageError as exc:
        raise ApiError(
            code="NOT_FOUND", message="Файл отсутствует", status_code=404
        ) from exc
    return Response(
        content=content,
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(file_name)},
    )


class InviteSpecialistIn(BaseModel):
    operator_id: uuid.UUID


@router.post("/tickets/{ticket_id}/specialists")
async def invite_specialist(
    ticket_id: uuid.UUID,
    payload: InviteSpecialistIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Owner (2026-11-23, plan item 7): invite a colleague as a specialist.

    They write from their own profile and can leave; the user is NOT
    notified. Allowed: the assignee, an active specialist, supervisor+.
    """
    deps = request.app.state.deps
    async with deps.db.session_factory() as session, session.begin():
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        allowed = (
            ticket.assignee_id == operator.id
            or operator.role != OperatorRole.OPERATOR
            or await ParticipantRepository().is_active_participant(
                session,
                conversation_id=ticket.conversation_id,
                operator_id=operator.id,
            )
        )
        if not allowed:
            raise ApiError(
                code="FORBIDDEN",
                message="Приглашать специалистов может назначенный сотрудник",
                status_code=403,
            )
        invitee = await session.get(Operator, payload.operator_id)
        if invitee is None or not invitee.is_active:
            raise ApiError(
                code="NOT_FOUND", message="Сотрудник не найден", status_code=404
            )
        if invitee.id == ticket.assignee_id:
            raise ApiError(
                code="STATE_CONFLICT",
                message="Сотрудник уже ведёт этот чат",
                status_code=409,
            )
        await ParticipantRepository().invite(
            session, conversation_id=ticket.conversation_id, operator_id=invitee.id
        )
        session.add(
            AuditLog(
                actor_type=AuditActorType.OPERATOR,
                actor_id=operator.id,
                action="specialist.invited",
                entity_type="conversation",
                entity_id=ticket.conversation_id,
                details={"specialist": invitee.email},
            )
        )
    await _notify_workspace(request)
    return {"ticket_id": str(ticket_id), "specialist_id": str(invitee.id)}


@router.post("/tickets/{ticket_id}/leave")
async def leave_as_specialist(
    ticket_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Owner (2026-11-23, plan item 7): a specialist leaves the dialog —
    silently, without notifying the user."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session, session.begin():
        ticket = await TicketRepository().get(session, ticket_id)
        if ticket is None:
            raise ApiError(code="NOT_FOUND", message="Ticket not found", status_code=404)
        left = await ParticipantRepository().leave(
            session, conversation_id=ticket.conversation_id, operator_id=operator.id
        )
        if not left:
            raise ApiError(
                code="STATE_CONFLICT",
                message="Вы не участник этого чата",
                status_code=409,
            )
        session.add(
            AuditLog(
                actor_type=AuditActorType.OPERATOR,
                actor_id=operator.id,
                action="specialist.left",
                entity_type="conversation",
                entity_id=ticket.conversation_id,
                details={},
            )
        )
    await _notify_workspace(request)
    return {"ticket_id": str(ticket_id), "left": True}


@router.post("/tickets/{ticket_id}/replies")
async def reply_to_ticket(    ticket_id: uuid.UUID,
    payload: ReplyIn,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Public reply (docs/06 §4): message + PENDING_USER + outbox, one tx."""
    if not payload.text.strip() and not payload.attachment_ids:
        raise ApiError(
            code="EMPTY_MESSAGE",
            message="Сообщение или вложение обязательно",
            status_code=422,
        )
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            result = await MessageService().add_operator_reply(
                session,
                ticket_id=ticket_id,
                text=payload.text,
                operator_id=operator.id,
                attachment_ids=payload.attachment_ids,
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
    return _note_view(note, operator.display_name or operator.email.split("@")[0])


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
        # Owner (2026-11-18): resolve note authors to display names.
        name_by_id: dict[uuid.UUID, str] = {}
        author_ids = {n.author_id for n in notes}
        if author_ids:
            rows = await session.execute(
                select(Operator).where(Operator.id.in_(author_ids))
            )
            for op in rows.scalars():
                name_by_id[op.id] = op.display_name or op.email.split("@")[0]
    return {
        "notes": [_note_view(n, name_by_id.get(n.author_id)) for n in notes]
    }


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
        user_names = await _user_name_map(session, [t.user_id for t in tickets])
        assignee_ids = {t.assignee_id for t in tickets if t.assignee_id}
        assignee_names: dict[Any, str] = {}
        if assignee_ids:
            rows = await session.scalars(
                select(Operator).where(Operator.id.in_(assignee_ids))
            )
            for op in rows:
                assignee_names[op.id] = op.display_name or op.email.split("@")[0]
        user_logins = await _user_login_map(session, [t.user_id for t in tickets])
    return {
        "tickets": [
            _ticket_view(
                ticket,
                tags=tag_map.get(ticket.id, []),
                user_name=user_names.get(ticket.user_id),
                assignee_name=assignee_names.get(ticket.assignee_id),
                user_login=user_logins.get(ticket.user_id),
            )
            for ticket in tickets
        ]
    }


@router.get("/users/{user_id}/ad-info")
async def user_ad_info(
    user_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
    force: bool = Query(default=False, description="Bypass the 24h cache"),
) -> dict[str, Any]:
    """Employee card from AD (P-29): org data, groups, password dates.

    Degrades to ``{"available": false}`` when AD is unreachable or no service
    account is configured; never blocks the ticket view. ``force=true`` is the
    operator's manual "Обновить из AD" action (owner 2026-11-17)."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        try:
            return await AdInfoService().get_for_user(session, user_id, force=force)
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


# Owner report (2026-11-20): when AD keeps no photo the avatar falls back
# to the Tag profile image. Small self-healing cache keyed by the Tag id.
_TAG_AVATAR_CACHE: dict[str, bytes] = {}
_TAG_AVATAR_CACHE_MAX = 256


@router.get("/users/{user_id}/tag-avatar")
async def user_tag_avatar(
    user_id: uuid.UUID,
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> Response:
    """Tag (Mattermost) profile image bytes; 404 when none is available."""
    settings = get_settings()
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise ApiError(code="NOT_FOUND", message="User not found", status_code=404)
        identities = await UserRepository().list_identities(session, user_id)
    external_id = next(
        (i.external_user_id for i in identities if i.external_user_id), None
    )
    if not external_id or not settings.tag_direct_mode:
        raise ApiError(code="NOT_FOUND", message="No Tag avatar", status_code=404)
    photo = _TAG_AVATAR_CACHE.get(external_id)
    if photo is None:
        photo = await fetch_tag_avatar(settings, external_id)
        if photo and len(_TAG_AVATAR_CACHE) >= _TAG_AVATAR_CACHE_MAX:
            _TAG_AVATAR_CACHE.clear()
        if photo:
            _TAG_AVATAR_CACHE[external_id] = photo
    if not photo:
        raise ApiError(code="NOT_FOUND", message="No Tag avatar", status_code=404)
    media_type = "image/png" if photo.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=photo, media_type=media_type)


class AdGroupOut(BaseModel):
    name: str = ""
    description: str = ""


class AdSearchOut(BaseModel):
    login: str = ""
    full_name: str = ""
    email: str = ""
    title: str = ""
    department: str = ""
    company: str = ""
    phone: str = ""
    disabled: bool = False
    # Owner (2026-11-17): groups carry descriptions (GetGroupBox layout);
    # the description comes from the SAME LDAP search — no extra latency.
    groups: list[AdGroupOut] = []
    mobile: str = ""
    manager: str = ""
    password_changed_at: str | None = None
    password_expires_at: str | None = None
    locked: bool = False
    demo: bool = False


def _normalize_ad_card(card: dict[str, Any]) -> AdSearchOut:
    changed = card.get("password_changed_at")
    expires = card.get("password_expires_at")
    groups: list[AdGroupOut] = []
    for group in card.get("groups") or []:
        if isinstance(group, dict):
            groups.append(
                AdGroupOut(
                    name=str(group.get("name") or ""),
                    description=str(group.get("description") or ""),
                )
            )
        else:
            groups.append(AdGroupOut(name=str(group)))
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
        groups=groups,
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
        # Owner request (2026-11-17): movements must show WHO, not "5D…".
        operator_ids = {
            event.actor_id
            for event in events
            if event.actor_id is not None
        } | {
            uuid.UUID(event.details["assignee_id"])
            for event in events
            if (event.details or {}).get("assignee_id")
        }
        operator_names = {
            operator.id: operator.display_name or operator.email
            for operator in (
                await session.scalars(
                    select(Operator).where(Operator.id.in_(operator_ids))
                )
            ).all()
        } if operator_ids else {}

        def _name(value: str | None) -> str | None:
            if value is None:
                return None
            return operator_names.get(uuid.UUID(value), None)

    return {
        "events": [
            {
                "action": event.action,
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "actor_name": _name(str(event.actor_id)) if event.actor_id else None,
                "assignee_id": (event.details or {}).get("assignee_id"),
                "assignee_name": _name((event.details or {}).get("assignee_id")),
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


@router.get("/kb")
async def list_active_kb_articles(
    operator: Annotated[Operator, Depends(require_operator)],
    request: Request,
) -> dict[str, Any]:
    """Owner (2026-11-23, plan item 8): active knowledge base articles for
    the composer — manual insert and typing hints."""
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        articles = await KbRepository().list_active(session)
    return {
        "articles": [
            {
                "article_id": str(article.id),
                "title": article.title,
                "body": article.body,
                "updated_at": article.updated_at.isoformat(),
            }
            for article in articles
        ]
    }
