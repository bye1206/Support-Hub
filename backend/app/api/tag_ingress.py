"""Tag ingress webhook: normalizes the bot callback and delegates to services.

No business logic here (AGENTS.md §6): schema validation, service-token
authentication and one service call. The transaction belongs to
MessageService (unit_of_work); this module only opens the session.
"""

import base64
import hmac
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.errors import ApiError
from app.infra.file_storage import FileStorageError, LocalFileStorage
from app.integrations.tag.direct import TagDirectSender
from app.integrations.tag.schemas import TagMessageIn
from app.repositories.attachments import AttachmentRepository
from app.repositories.channels import ChannelRepository
from app.repositories.tickets import TicketRepository
from app.services.messages import IncomingFile, MessageService
from app.services.ratings import RatingService

router = APIRouter(prefix="/api/v1/integrations/tag", tags=["tag-integration"])

logger = logging.getLogger(__name__)


async def require_bot_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Service auth for the inbound webhook (11.A.1 open; shared-secret PROPOSED)."""
    configured = get_settings().bot_webhook_token
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise ApiError(
            code="SERVICE_UNAUTHORIZED",
            message="Invalid or missing bot service token",
            status_code=401,
        )


class TagMessageResult(BaseModel):
    """Everything the bot (and its alerting) may need; no internal-only data."""

    message_id: str
    conversation_id: str
    ticket_id: str
    sequence_no: int
    conversation_created: bool
    ticket_reopened: bool
    deduplicated: bool


async def _resolve_incoming_files(event: TagMessageIn) -> list[IncomingFile]:
    """Owner request (2026-11-19): decode/fetch the files the user attached.

    base64 is decoded inline; `url` files are downloaded here so the service
    layer stays transport-agnostic. A failed download rejects the callback
    (the bot retries the whole message).
    """
    import binascii

    import httpx

    files: list[IncomingFile] = []
    for file in event.files:
        if file.content_b64:
            try:
                content = base64.b64decode(file.content_b64)
            except (ValueError, binascii.Error) as exc:
                raise ApiError(
                    code="BAD_ATTACHMENT",
                    message=f"Некорректный файл {file.file_name}",
                    status_code=422,
                ) from exc
            files.append(
                IncomingFile(
                    file_name=file.file_name,
                    mime_type=file.mime_type,
                    content=content,
                )
            )
        elif file.url:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(file.url)
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ApiError(
                    code="ATTACHMENT_FETCH_FAILED",
                    message=f"Не удалось скачать {file.file_name}",
                    status_code=502,
                ) from exc
            files.append(
                IncomingFile(
                    file_name=file.file_name,
                    mime_type=file.mime_type,
                    content=response.content,
                )
            )
    return files


@router.post(
    "/messages",
    response_model=TagMessageResult,
    dependencies=[Depends(require_bot_token)],
)
async def receive_message(request: Request, event: TagMessageIn) -> TagMessageResult:
    """One user message from Tag via the existing bot (docs/04 §4)."""
    files = await _resolve_incoming_files(event)
    if not event.text.strip() and not files:
        raise ApiError(
            code="EMPTY_MESSAGE",
            message="Сообщение или вложение обязательно",
            status_code=422,
        )
    deps = request.app.state.deps
    async with deps.db.session_factory() as session:
        channel = await ChannelRepository().get_or_create(
            session,
            channel_type="tag",
            external_channel_id=event.channel_id,
            display_name=event.channel_name,
        )
        result = await MessageService().handle_incoming_user_message(
            session,
            channel_type="tag",
            external_user_id=event.user_id,
            external_user_name=event.user_name,
            text=event.text,
            external_post_id=event.post_id,
            source_created_at=event.source_created_at,
            channel_id=channel.id,
            files=files,
        )
    return TagMessageResult(
        message_id=str(result.message.id),
        conversation_id=str(result.conversation.id),
        ticket_id=str(result.ticket.id),
        sequence_no=result.message.sequence_no,
        conversation_created=result.conversation_created,
        ticket_reopened=result.ticket_reopened,
        deduplicated=result.deduplicated,
    )


@router.get("/attachments/{attachment_id}/file")
async def bot_download_attachment(
    attachment_id: uuid.UUID,
    request: Request,
    token: str = "",
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Outbound attachment download for the bot (PROPOSED contract addition).

    Auth: same shared-secret token as the webhook (query param or Bearer).
    """
    supplied = token or (
        authorization.removeprefix("Bearer ").strip() if authorization else ""
    )
    configured = get_settings().bot_webhook_token
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise ApiError(
            code="SERVICE_UNAUTHORIZED",
            message="Invalid or missing bot service token",
            status_code=401,
        )
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
    from urllib.parse import quote

    ascii_fallback = file_name.encode("ascii", "ignore").decode() or "file"
    return Response(
        content=content,
        media_type=mime or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_fallback}\"; "
                f"filename*=UTF-8''{quote(file_name)}"
            )
        },
    )


class RatingButtonContext(BaseModel):
    """The context Mattermost echoes back when a rating button is clicked."""

    ticket_id: uuid.UUID
    score: int


@router.post("/rating")
async def rating_button(
    request: Request,
    token: str = "",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Mattermost interactive-button callback (owner request, 2026-11-19).

    The five buttons (5..1) on the closure note post here with the button
    context. Auth mirrors the attachment download: shared secret as a
    query param or Bearer. The thanks / review-request note is delivered
    through our own outbox pipeline, so the response body stays empty.
    """
    supplied = token or (
        authorization.removeprefix("Bearer ").strip() if authorization else ""
    )
    configured = get_settings().bot_webhook_token
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise ApiError(
            code="SERVICE_UNAUTHORIZED",
            message="Invalid or missing bot service token",
            status_code=401,
        )
    try:
        body = await request.json()
    except Exception:
        body = {}
    context = body.get("context") or {}
    logger.info(
        "Rating click: context keys=%s post_id=%s",
        sorted(context.keys()),
        bool(body.get("post_id")),
    )
    try:
        parsed = RatingButtonContext.model_validate(context)
    except Exception:
        logger.warning("Rating click: unparsable context, dropped")
        return {}
    deps = request.app.state.deps
    # Owner bugfix (2026-11-25): this used to be a plain session without a
    # transaction - capture_score flushed the rating, the session closed,
    # and the INSERT ROLLED BACK. Ratings never persisted at all (the
    # owner's 'оценок нигде нет'). Explicit commit like every other route.
    async with deps.db.session_factory() as session, session.begin():
        ticket = await TicketRepository().get(session, parsed.ticket_id)
        if ticket is None:
            logger.warning(
                "Rating click: ticket %s not found, dropped", parsed.ticket_id
            )
            return {}
        await RatingService().capture_score(session, ticket, parsed.score)
    logger.info(
        "Rating click: captured score=%s ticket=%s", parsed.score, parsed.ticket_id
    )
    # Owner (2026-11-25): replace the button card with a thank-you note —
    # the orchestrator relays the click WITH post_id, we own the bot token.
    # Best-effort: a failed edit leaves the buttons, a repeat click just
    # overwrites the score. Must not break the <=5s response contract.
    card_post_id = str(body.get("post_id") or "")
    if card_post_id:
        try:
            sender = TagDirectSender(get_settings())
            try:
                await sender.replace_post_card(
                    card_post_id,
                    f"Спасибо за оценку {parsed.score}/5!",
                )
            finally:
                await sender.aclose()
        except Exception:  # noqa: BLE001 - cosmetic, never fails the click
            pass
    return {}
