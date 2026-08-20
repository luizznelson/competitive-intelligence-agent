from __future__ import annotations

import json


class QuestionValidationError(ValueError):
    """Raised when a public AI question does not satisfy input limits."""


def normalize_question(question: str, max_chars: int) -> str:
    """Validate and normalize a user question before it reaches the LLM."""
    raw = (question or "").strip()
    if not raw:
        raise QuestionValidationError("Digite uma pergunta antes de analisar.")
    if len(raw) > max_chars:
        raise QuestionValidationError(
            f"A pergunta deve ter no máximo {max_chars} caracteres."
        )
    return " ".join(raw.split())


def tool_call_signature(name: str, arguments: str | dict | None) -> str:
    """Build a stable signature used to block repeated tool calls in one request."""
    if isinstance(arguments, str):
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            payload = {"_raw": arguments}
    else:
        payload = arguments or {}
    return f"{name}:{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
