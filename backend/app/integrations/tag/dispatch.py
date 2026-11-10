"""Routing dispatcher: maps outbox event types to delivery consumers.

- message.outbound -> TagBotClient (stage 5)
- message.user_received -> AI orchestration trigger (stage 6; log-only here)
- anything else -> log (proves the pipeline without discarding events silently)
"""

import logging
from typing import Protocol

from app.config import get_settings
from app.integrations.tag import bot_client
from app.integrations.tag.bot_client import TagBotClient
from app.models import OutboxEvent
from app.services.outbox import LoggingOutboxHandler

logger = logging.getLogger(__name__)

BOT_MESSAGES_PATH = bot_client.BOT_MESSAGES_PATH


class _FallbackHandler(Protocol):
    async def __call__(self, event: OutboxEvent) -> None: ...


class _BotSender(Protocol):
    async def send_message(self, payload: dict) -> None: ...


class RoutingOutboxHandler:
    """Dispatch one leased outbox event to its consumer by event_type."""

    def __init__(self, bot: _BotSender, fallback: _FallbackHandler) -> None:
        self._bot = bot
        self._fallback = fallback

    async def __call__(self, event: OutboxEvent) -> None:
        if event.event_type == "message.outbound":
            # Payload keys are produced by MessageService, never client input.
            await self._bot.send_message(event.payload)
            return
        await self._fallback(event)


def build_default_outbox_handler() -> RoutingOutboxHandler:
    """Production wiring: real bot client + LoggingOutboxHandler as fallback."""
    settings = get_settings()
    # LoggingOutboxHandler covers stage-6 events (AI trigger) until stage 6.
    bot = TagBotClient(
        base_url=settings.bot_internal_base_url,
        service_token=(settings.support_hub_to_bot_token or None),
    )
    return RoutingOutboxHandler(bot=bot, fallback=LoggingOutboxHandler())
