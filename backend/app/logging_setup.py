"""JSON logging with correlation ID and secret masking.

Full structured logging policy (field allowlist, request bodies) lands later;
this module owns the format every component reuses.
"""

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

from app.secrets_masking import mask_secrets

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_secrets(record.getMessage()),
            "correlation_id": correlation_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
