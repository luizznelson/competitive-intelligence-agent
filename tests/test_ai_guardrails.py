import pytest

from src.competitive_intelligence.ai_guardrails import (
    QuestionValidationError,
    normalize_question,
    tool_call_signature,
)


def test_normalize_question_trims_and_collapses_whitespace():
    assert normalize_question("  qual   produto\n merece atenção?  ", 100) == "qual produto merece atenção?"


def test_normalize_question_rejects_empty():
    with pytest.raises(QuestionValidationError):
        normalize_question("   ", 100)


def test_normalize_question_rejects_oversized_input():
    with pytest.raises(QuestionValidationError):
        normalize_question("x" * 101, 100)


def test_tool_call_signature_is_stable_for_json_key_order():
    a = tool_call_signature("compare_prices", '{"b": 2, "a": 1}')
    b = tool_call_signature("compare_prices", '{"a": 1, "b": 2}')
    assert a == b


def test_tool_call_signature_separates_different_arguments():
    a = tool_call_signature("compare_prices", '{"product": "a"}')
    b = tool_call_signature("compare_prices", '{"product": "b"}')
    assert a != b
