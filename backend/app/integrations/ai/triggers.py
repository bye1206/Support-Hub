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
import re

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


# Owner (2026-11-23): an explicit operator request escalates INSTANTLY on
# ingest — the gateway roundtrip (worst case: a 115 s RAG timeout) must not
# stand between the user and a human. The message must be a short request
# built from operator words and politeness filler; a message that merely
# MENTIONS an operator ("оператор сотовой связи не работает") does not match.
_OPERATOR_STEMS = (
    "оператор",
    "человек",
    "люд",
    "специалист",
)
_OPERATOR_FILLERS = frozenset(
    {
        "позовите",
        "позов",
        "дайте",
        "дай",
        "мне",
        "нужен",
        "нужна",
        "нужны",
        "пожалуйста",
        "пж",
        "живой",
        "живого",
        "реальный",
        "реального",
        "хочу",
        "общаться",
        "поговорить",
        "со",
        "с",
        "и",
        "а",
    }
)
_OPERATOR_REQUEST_MAX_WORDS = 6


def operator_requested(text: str) -> bool:
    """True when the message is itself a request for a human operator."""
    words = re.findall(r"[а-яёa-z]+", text.lower())
    if not words or len(words) > _OPERATOR_REQUEST_MAX_WORDS:
        return False
    has_operator_word = False
    for word in words:
        if word.startswith(_OPERATOR_STEMS):
            has_operator_word = True
        elif word not in _OPERATOR_FILLERS:
            return False
    return has_operator_word
