"""Secret masking and JSON log format tests."""

import logging

from app.logging_setup import JsonFormatter, correlation_id_var
from app.secrets_masking import mask_secrets


def test_mask_bearer_token() -> None:
    assert mask_secrets("Authorization: Bearer eyJhbGciOi.abc") == "Authorization: Bearer ***"


def test_mask_key_value_secrets() -> None:
    assert mask_secrets("password=hunter2") == "password=***"
    assert mask_secrets("MINIO_SECRET_KEY: supersecret") == "MINIO_SECRET_KEY: ***"
    assert mask_secrets("token=abc123") == "token=***"


def test_mask_keeps_normal_text() -> None:
    text = "Ticket 123 created by operator ivanov"
    assert mask_secrets(text) == text


def test_json_formatter_contains_correlation_id_and_masks() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Auth header seen: Authorization: Bearer secret-token-value",
        args=(),
        exc_info=None,
    )
    correlation_id_var.set("corr-123")
    rendered = formatter.format(record)

    assert '"correlation_id": "corr-123"' in rendered
    assert "secret-token-value" not in rendered
    assert "Bearer ***" in rendered
    correlation_id_var.set("-")
