"""Tag ingress webhook: normalizes the bot callback and delegates to services.

No business logic here (AGENTS.md §6): schema validation, service-token
authentication and one service call. The transaction belongs to
MessageService (unit_of_work); this module only opens the session.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from app.config import get_settings
from app.errors import ApiError
from app.integrations.tag.schemas import TagMessageIn
from app.repositories.channels import ChannelRepository
from app.services.messages import MessageService

router = APIRouter(prefix="/api/v1/integrations/tag", tags=["tag-integration"])


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


@router.post(
    "/messages",
    response_model=TagMessageResult,
    dependencies=[Depends(require_bot_token)],
)
async def receive_message(request: Request, event: TagMessageIn) -> TagMessageResult:
    """One user message from Tag via the existing bot (docs/04 §4)."""
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
