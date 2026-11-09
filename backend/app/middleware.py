"""Pure ASGI middleware: assigns a correlation ID to every HTTP request.

An incoming `X-Request-ID` is reused only when it matches a safe pattern,
otherwise a new ID is generated. The ID is exposed to logging via ContextVar
and returned to the client in the `X-Request-ID` response header.
"""

import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_setup import correlation_id_var

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id")
        if incoming and _SAFE_REQUEST_ID.fullmatch(incoming):
            correlation_id = incoming
        else:
            correlation_id = uuid.uuid4().hex

        token = correlation_id_var.set(correlation_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("x-request-id", correlation_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_var.reset(token)
