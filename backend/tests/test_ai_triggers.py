"""Unit tests of the gateway trigger-code detection (D-043 §7).

Policy under test (PROPOSED, owner confirmation pending): exact configured
codes act; unknown code-LIKE answers are rendered as text (a user typing
"abc123" must not take the dialog over); free text never triggers.
"""

from app.integrations.ai.triggers import detect_trigger, is_trigger_like

RESOLVED_CODE = "hnQRDemsuPZY"  # contract v1.0 default (settings default)
OPERATOR_CODE = "tY7Ve077FyZR1"


def test_resolved_code_detected() -> None:
    assert detect_trigger(RESOLVED_CODE) == "RESOLVED"


def test_operator_code_detected() -> None:
    assert detect_trigger(OPERATOR_CODE) == "OPERATOR"


def test_codes_are_matched_after_strip() -> None:
    assert detect_trigger(f"  {RESOLVED_CODE} ") == "RESOLVED"


def test_normal_text_is_not_a_trigger() -> None:
    assert detect_trigger("Попробуйте перезагрузить роутер") is None


def test_unknown_code_like_answer_is_not_a_trigger() -> None:
    # Code-like but NOT a configured code: rendered as text, never acts.
    assert detect_trigger("abc123") is None
    assert is_trigger_like("abc123")


def test_free_text_is_not_trigger_like() -> None:
    assert not is_trigger_like("вот ваш ответ, его тут много слов")
    assert not is_trigger_like("")


def test_long_token_without_digit_is_not_trigger_like() -> None:
    assert not is_trigger_like("a" * 40)
