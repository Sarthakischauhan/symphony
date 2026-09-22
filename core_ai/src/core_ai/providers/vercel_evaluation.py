"""Vercel AI Gateway evaluation-model endpoint.

Language models stay on OpenAI-compatible Chat Completions in ``vercel.py``.
Evaluation models such as ``typesafe-ai/jev`` use:

``POST https://ai-gateway.vercel.sh/v4/ai/evaluation-model``
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.content import text_from_content
from core_ai.providers.openai import _raise_if_http_error
from core_ai.types import Message, StreamEvent

EVALUATION_SPEC_VERSION = "4"
EVALUATION_MODEL_PATH = "evaluation-model"
_EVALUATION_MODEL_MARKERS = ("typesafe-ai/jev", "/jev", "-jev")


def evaluation_model_url(base_url: str = "") -> str:
    """Return the Gateway evaluation-model URL for a chat or protocol base."""
    from core_ai.providers.vercel import vercel_gateway_base_url

    return f"{vercel_gateway_base_url(base_url)}/{EVALUATION_MODEL_PATH}"


def evaluation_request_headers(
    model_name: str,
    *,
    api_key: str,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ai-evaluation-model-specification-version": EVALUATION_SPEC_VERSION,
        "ai-gateway-protocol-version": "0.0.1",
        "ai-model-id": model_name,
        **(extra_headers or {}),
    }


def is_evaluation_model(model_name: str) -> bool:
    """True for Gateway evaluation models such as ``typesafe-ai/jev``."""
    raw = (model_name or "").strip().lower()
    if not raw:
        return False
    if raw.endswith("-eval") or raw.startswith("eval/") or "/eval-" in raw:
        return True
    return any(marker in raw for marker in _EVALUATION_MODEL_MARKERS)


def evaluation_request_body(
    messages: List[Message],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    reasoning_effort: Optional[str] = None,
) -> dict[str, Any]:
    """Map Symphony messages onto the experimental evaluation-model request."""
    explicit = _explicit_evaluation_payload(messages)
    state = explicit.get("state") if explicit else None
    questions = explicit.get("questions") if explicit else None
    if not isinstance(questions, dict) or not questions:
        questions = _questions_for(messages, tools or [])
    if state is None:
        state = _evaluation_state(messages)
    body: dict[str, Any] = {"state": state, "questions": questions}
    if reasoning_effort:
        body["providerOptions"] = {"reasoning": {"effort": reasoning_effort}}
    return body


def format_evaluation_answers(answers: object) -> str:
    if not isinstance(answers, dict) or not answers:
        return ""
    lines: list[str] = []
    for name, answer in answers.items():
        formatted = _format_evaluation_answer(answer)
        if formatted:
            lines.append(f"{name}: {formatted}" if len(answers) > 1 else formatted)
    return "\n".join(lines)


async def stream_evaluation_model(
    *,
    model_name: str,
    messages: List[Message],
    api_key: str,
    base_url: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    reasoning_effort: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> AsyncGenerator[StreamEvent, None]:
    """POST ``/v4/ai/evaluation-model`` and yield harness-compatible events."""
    payload = evaluation_request_body(
        messages,
        tools=tools,
        reasoning_effort=reasoning_effort,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            evaluation_model_url(base_url),
            json=payload,
            headers=evaluation_request_headers(
                model_name,
                api_key=api_key,
                extra_headers=extra_headers,
            ),
            timeout=60.0,
        )
        await _raise_if_http_error(response)
        body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("evaluation model returned a non-object response")
    async for event in _evaluation_events(body, tools or []):
        yield event


def _explicit_evaluation_payload(messages: List[Message]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.role != "user":
            continue
        raw = text_from_content(message.content).strip()
        if not raw.startswith("{") and not raw.startswith("["):
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(parsed, dict) and isinstance(parsed.get("questions"), dict):
            return parsed
        return {}
    return {}


def _questions_for(
    messages: List[Message], tools: List[Dict[str, Any]]
) -> dict[str, Any]:
    if tools:
        criteria = {
            str(tool.get("name") or f"tool_{index}"): str(
                tool.get("description") or tool.get("name") or "tool"
            )
            for index, tool in enumerate(tools)
            if isinstance(tool, dict)
        }
        criteria["reply"] = "Respond to the user without calling a tool."
        return {
            "next_action": {
                "type": "choice",
                "instructions": (
                    "Choose the tool the assistant should call next, or reply if "
                    "no tool is needed."
                ),
                "criteria": criteria,
            }
        }
    last_user = _last_user_text(messages)
    return {
        "response": {
            "type": "boolean",
            "instructions": last_user
            or "Should the assistant continue helping with this request?",
        }
    }


def _last_user_text(messages: List[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return text_from_content(message.content).strip()
    return ""


def _evaluation_state(messages: List[Message]) -> str:
    chunks: list[str] = []
    for message in messages:
        text = text_from_content(message.content).strip()
        if message.role == "tool":
            prefix = f"tool({message.tool_call_id})" if message.tool_call_id else "tool"
            chunks.append(f"{prefix}: {text}" if text else f"{prefix}:")
            continue
        if message.tool_calls:
            names = [
                _tool_call_name(call) for call in message.tool_calls if _tool_call_name(call)
            ]
            extra = f" [tools: {', '.join(names)}]" if names else ""
            chunks.append(f"{message.role}{extra}: {text}".rstrip())
            continue
        if text:
            chunks.append(f"{message.role}: {text}")
    return "\n\n".join(chunks)


def _tool_call_name(call: object) -> str:
    if not isinstance(call, dict):
        return ""
    function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "").strip()
    return str(call.get("name") or "").strip()


def _format_evaluation_answer(answer: object) -> str:
    if not isinstance(answer, dict):
        return json.dumps(answer)
    kind = str(answer.get("type") or "")
    if kind == "choice":
        return str(answer.get("choice") or "")
    if kind == "score":
        score = answer.get("score")
        return "" if score is None else str(score)
    if kind == "boolean":
        probability = answer.get("probability")
        if isinstance(probability, (int, float)):
            return "true" if probability >= 0.5 else "false"
        return "true" if answer.get("value") else "false"
    return json.dumps(answer)


async def _evaluation_events(
    body: dict[str, Any], tools: List[Dict[str, Any]]
) -> AsyncGenerator[StreamEvent, None]:
    answers = body.get("answers")
    tool_names = {
        str(tool.get("name") or "")
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    }
    next_action = None
    if isinstance(answers, dict):
        next_action = answers.get("next_action")
    choice = ""
    if isinstance(next_action, dict) and next_action.get("type") == "choice":
        choice = str(next_action.get("choice") or "").strip()
    if choice and choice in tool_names:
        yield StreamEvent(
            type="toolcall_start",
            content_index=0,
            tool_call_id="eval_next_action",
            tool_name=choice,
        )
        yield StreamEvent(
            type="toolcall_delta",
            content_index=0,
            delta="{}",
        )
    else:
        text = format_evaluation_answers(answers)
        if text:
            yield StreamEvent(type="text_delta", content_index=0, delta=text)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    if usage:
        prompt_tokens = usage.get("inputTokens", usage.get("prompt_tokens"))
        completion_tokens = usage.get("outputTokens", usage.get("completion_tokens"))
        total_tokens = usage.get("total_tokens")
        if total_tokens is None and isinstance(prompt_tokens, int) and isinstance(
            completion_tokens, int
        ):
            total_tokens = prompt_tokens + completion_tokens
        yield StreamEvent(
            type="usage",
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=(
                completion_tokens if isinstance(completion_tokens, int) else None
            ),
            total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        )
    yield StreamEvent(type="done", content_index=0)


__all__ = [
    "EVALUATION_MODEL_PATH",
    "EVALUATION_SPEC_VERSION",
    "evaluation_model_url",
    "evaluation_request_body",
    "evaluation_request_headers",
    "format_evaluation_answers",
    "is_evaluation_model",
    "stream_evaluation_model",
]
