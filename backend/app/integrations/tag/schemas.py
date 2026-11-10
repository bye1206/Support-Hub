"""Tag callback payload schema and normalization.

Field list is owner-provided (AGENTS.md §5, D-027): the bot callback contains
team_id, team_domain, channel_id, channel_name, timestamp, user_id, user_name,
post_id, text, file_ids. Optional flags are defensive: exact payload of the
existing bot must be verified when the corporate network is available (11.A).
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Heuristics for epoch timestamps above/below these bounds:
# >1e12 means milliseconds (date 2001+), >1e9 means seconds.
_EPOCH_MS_BOUND = 10**12
_EPOCH_S_BOUND = 10**9


def parse_source_timestamp(raw: Any) -> datetime | None:
    """Normalize Tag `timestamp` without assuming its unit (11.A.2 is open).

    Accepts ISO-8601 strings (the safest exchange format) and numeric epochs
    (seconds/milliseconds autodetected by magnitude; nanoseconds trimmed down
    to seconds by magnitude). Returns None for empty input, raises ValueError
    for anything unparseable so the caller can reject the callback.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value >= _EPOCH_MS_BOUND:  # milliseconds
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        if value >= _EPOCH_S_BOUND:  # seconds
            return datetime.fromtimestamp(value, tz=UTC)
        raise ValueError(f"Timestamp looks too small to be an epoch: {raw!r}")
    text = str(raw).strip()
    if text.isdigit():
        return parse_source_timestamp(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Unparsable timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class TagMessageIn(BaseModel):
    """Normalized user-message callback from the existing bot."""

    model_config = ConfigDict(extra="allow")

    team_id: str
    team_domain: str | None = None
    channel_id: str
    channel_name: str | None = None
    timestamp: str | int | float | None = None
    user_id: str
    user_name: str | None = None
    post_id: str | None = None
    text: str = Field(min_length=1)
    file_ids: list[str] = Field(default_factory=list)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_parseable(cls, value: Any) -> Any:
        parse_source_timestamp(value)
        return value

    @property
    def source_created_at(self) -> datetime | None:
        return parse_source_timestamp(self.timestamp)
