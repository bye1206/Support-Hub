"""Gateway trigger codes (D-043 §7): the answer may be a short code, not text.

Codes are alphanumeric, <= 30 chars, no spaces, at least one digit. Two codes
are defined in the contract v1.0; they can be ROTATED on the gateway side
(integration team notifies in advance) - configured via settings, not hardcoded.

Detection policy (PROPOSED, owner confirmation pending):
- exact match of a configured code -> act (resolve / hand off);
- a code-LIKE answer that is NOT a configured code is rendered as text and
  logged: treating unknown codes as triggers would let any user typing
  "abc123" take the dialog over.
"""

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_CODE_LENGTH = 30


class TriggerKind:
    RESOLVED = "RESOLVED"
    OPERATOR = "OPERATOR"


def is_trigger_like(answer: str) -> bool:
    """The contract's own guard recipe (§7): short alnum token with a digit."""
    code = answer.strip()
    no_spaces = " " not in code
    return len(code) <= MAX_CODE_LENGTH and no_spaces and code.isalnum() and not code.isalpha()


def detect_trigger(answer: str) -> str | None:
    """Return the trigger kind for a configured code, else None."""
    kind_by_code = {
        get_settings().ai_trigger_resolved_code: TriggerKind.RESOLVED,
        get_settings().ai_trigger_operator_code: TriggerKind.OPERATOR,
    }
    code = answer.strip()
    kind = kind_by_code.get(code)
    if kind is not None:
        return kind
    if is_trigger_like(code):
        # A rotated/unrecognized code: do not act on it, do not hide it.
        logger.warning("Unrecognized trigger-like gateway answer (len=%s)", len(code))
    return None
