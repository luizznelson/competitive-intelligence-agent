from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import TextContent

from .ai_guardrails import normalize_question, tool_call_signature
from .config import (
    AI_GROQ_TIMEOUT_SECONDS,
    AI_MAX_COMPLETION_TOKENS,
    AI_MAX_QUESTION_CHARS,
    AI_MAX_STEPS,
    AI_MAX_TOOL_CALLS,
    AI_MAX_TOOL_RESULT_CHARS,
    GROQ_MODEL,
    ROOT,
)

load_dotenv(ROOT / ".env")

SYSTEM_PROMPT = """Você é um analista de inteligência competitiva.
Use as ferramentas disponíveis para responder somente com base nos dados coletados pelo sistema.
Nunca invente preços, movimentos, disponibilidade ou tendências.
Quando houver poucos dados históricos, deixe isso explícito e diferencie fotografia atual de tendência.
Diferencie fatos observados de interpretação.
Não recomende alteração de preço automaticamente: destaque evidências, riscos e pontos que merecem análise humana.
Quando fizer sentido, organize a resposta em: Achado, Evidência e Limitação/Próximo passo.
Se já tiver informação suficiente, responda sem chamar novas ferramentas.
Não repita a mesma chamada de ferramenta na mesma análise.
Responda em português do Brasil de forma executiva, clara e objetiva.
Sua resposta final tem um orçamento de tokens limitado: seja direto, priorize os 2-3 pontos mais
relevantes em vez de cobrir todos os dados disponíveis, e nunca gaste esse orçamento em raciocínio
interno — vá direto à resposta.
"""


class AgentRateLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: str | None = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Limite temporário da API de IA atingido.")


class AgentTemporaryError(RuntimeError):
    pass


class AgentBudgetError(RuntimeError):
    pass


def _tool_schema(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


def _tool_result_text(result) -> str:
    blocks = [block.text for block in result.content if isinstance(block, TextContent)]
    if blocks:
        text = "\n".join(blocks)
    else:
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        text = json.dumps(structured, ensure_ascii=False, default=str) if structured is not None else "[]"

    if len(text) > AI_MAX_TOOL_RESULT_CHARS:
        return text[:AI_MAX_TOOL_RESULT_CHARS] + "\n[resultado truncado pelo limite de segurança]"
    return text


def _status_code(exc: Exception) -> int | None:
    direct = getattr(exc, "status_code", None)
    if isinstance(direct, int):
        return direct
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _retry_after(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        return headers.get("retry-after") or headers.get("Retry-After")
    return None


def _raise_safe_api_error(exc: Exception) -> None:
    status = _status_code(exc)
    if status == 429:
        raise AgentRateLimitError(_retry_after(exc)) from exc
    if status is not None and status >= 500:
        raise AgentTemporaryError("O provedor de IA está temporariamente indisponível.") from exc
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "connection" in name:
        raise AgentTemporaryError("Não foi possível conectar ao provedor de IA no momento.") from exc
    raise exc


async def ask_agent(
    question: str,
    max_steps: int | None = None,
    max_tool_calls: int | None = None,
) -> str:
    """Run a bounded, single-request analysis over deterministic MCP tools."""
    question = normalize_question(question, AI_MAX_QUESTION_CHARS)
    step_budget = AI_MAX_STEPS if max_steps is None else max(1, min(AI_MAX_STEPS, max_steps))
    tool_budget = AI_MAX_TOOL_CALLS if max_tool_calls is None else max(1, min(AI_MAX_TOOL_CALLS, max_tool_calls))

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY não configurada. Em produção, adicione a chave aos Secrets do Streamlit Cloud."
        )

    # Disable hidden SDK retries: one model request per explicit agent step.
    # This keeps public usage bounded and avoids retry storms on 429 responses.
    groq = Groq(
        api_key=api_key,
        max_retries=0,
        timeout=AI_GROQ_TIMEOUT_SECONDS,
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.competitive_intelligence.mcp_server"],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    async with Client(stdio_client(params)) as client:
        tool_list = await client.list_tools()
        tools = [_tool_schema(tool) for tool in tool_list.tools]

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        used_tool_calls = 0
        seen_tool_calls: set[str] = set()

        # Reasoning-capable models (the default openai/gpt-oss-20b included) can burn the
        # entire max_completion_tokens budget on hidden chain-of-thought and return an
        # empty final answer with finish_reason == "tool_calls" and content == None.
        # Capping reasoning effort leaves tokens for the actual answer. Only sent for
        # models known to support it, since Groq rejects unknown fields for others.
        extra_params = {"reasoning_effort": "low"} if "gpt-oss" in GROQ_MODEL else {}

        for _ in range(step_budget):
            try:
                response = groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                    max_completion_tokens=AI_MAX_COMPLETION_TOKENS,
                    **extra_params,
                )
            except Exception as exc:  # SDK exception classes vary across supported versions.
                _raise_safe_api_error(exc)
                raise  # pragma: no cover

            message = response.choices[0].message
            assistant_payload = {
                "role": "assistant",
                "content": message.content or "",
            }
            if message.tool_calls:
                assistant_payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(assistant_payload)

            if not message.tool_calls:
                return message.content or "Sem resposta textual do modelo."

            if used_tool_calls + len(message.tool_calls) > tool_budget:
                raise AgentBudgetError(
                    "A análise atingiu o limite seguro de consultas às ferramentas. Reformule a pergunta de forma mais específica."
                )

            for call in message.tool_calls:
                signature = tool_call_signature(call.function.name, call.function.arguments)
                if signature in seen_tool_calls:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.function.name,
                            "content": (
                                "Chamada repetida bloqueada pelo limite de segurança. "
                                "Use as evidências já obtidas e conclua a resposta."
                            ),
                        }
                    )
                    continue

                seen_tool_calls.add(signature)
                used_tool_calls += 1
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await client.call_tool(call.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": _tool_result_text(result),
                    }
                )

        raise AgentBudgetError(
            "A análise atingiu o limite seguro de etapas antes de concluir. Faça uma pergunta mais específica."
        )


def ask_agent_sync(question: str) -> str:
    return asyncio.run(ask_agent(question))
