"""Vercel AI Gateway via OpenAI-compatible Chat Completions and evaluations.

The Vercel AI SDK talks to this gateway. Symphony uses the same HTTP surface
rather than embedding the TypeScript SDK:

- language models: ``POST https://ai-gateway.vercel.sh/v1/chat/completions``
- evaluation models (for example ``typesafe-ai/jev``):
  ``POST https://ai-gateway.vercel.sh/v4/ai/evaluation-model``
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.content import text_from_content
from core_ai.models import get_model
from core_ai.providers.http import stream_with_retries
from core_ai.providers.ollama import openai_compatible_model_ids
from core_ai.providers.openai import (
    OpenAIProvider,
    _raise_if_http_error,
    openai_compat_base_url,
)
from core_ai.types import Message, StreamEvent

VERCEL_DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
VERCEL_DEFAULT_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v4/ai"
DISCOVER_TIMEOUT = 8.0
EVALUATION_SPEC_VERSION = "4"
_EVALUATION_MODEL_MARKERS = ("typesafe-ai/jev", "/jev", "-jev")
_NON_LANGUAGE_TYPES = {
    "embedding",
    "embeddings",
    "image",
    "video",
    "audio",
    "reranking",
    "rerank",
}


class VercelProvider(OpenAIProvider):
    """Vercel AI Gateway chat completions and evaluation models."""

    include_stream_options = True
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str,
        base_url: str = VERCEL_DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=vercel_chat_base_url(base_url) or VERCEL_DEFAULT_BASE_URL,
            transport=transport,
            extra_headers=extra_headers,
        )

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        if is_evaluation_model(model_name):
            async for event in stream_with_retries(
                lambda: self._stream_evaluation(
                    model_name, messages, tools, reasoning_effort
                )
            ):
                yield event
            return
        async for event in super().stream(
            model_name, messages, tools, max_output_tokens, reasoning_effort
        ):
            yield event

    async def _stream_evaluation(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        payload = evaluation_request_body(
            messages,
            tools=tools,
            reasoning_effort=reasoning_effort,
        )
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.post(
                evaluation_model_url(self.base_url),
                json=payload,
                headers=evaluation_request_headers(
                    model_name,
                    api_key=self.api_key,
                    extra_headers=self.extra_headers,
                ),
                timeout=60.0,
            )
            await _raise_if_http_error(response)
            body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("evaluation model returned a non-object response")
        async for event in _evaluation_events(body, tools or []):
            yield event

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return not is_evaluation_model(model_name)

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("vercel", model_name)
        return bool(model is not None and model.reasoning)

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        del model_name, prompt, output_format
        raise NotImplementedError("VercelProvider does not support image generation")


def vercel_chat_base_url(value: str = "") -> str:
    return openai_compat_base_url(value, default=VERCEL_DEFAULT_BASE_URL)


def vercel_gateway_base_url(value: str = "") -> str:
    """Normalize a host or OpenAI-compat URL to the Gateway protocol ``.../v4/ai`` base."""
    raw = (value or "").strip()
    if raw:
        normalized = raw if "://" in raw else f"http://{raw}"
        normalized = normalized.rstrip("/")
        if normalized.endswith("/v4/ai"):
            return normalized
    chat_url = vercel_chat_base_url(value)
    if chat_url.endswith("/v1"):
        return f"{chat_url[:-3]}/v4/ai"
    return VERCEL_DEFAULT_GATEWAY_BASE_URL


def evaluation_model_url(base_url: str = "") -> str:
    return f"{vercel_gateway_base_url(base_url)}/evaluation-model"


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


def discover_vercel_models(
    base_url: str = VERCEL_DEFAULT_BASE_URL,
    *,
    api_key: str,
    timeout: float = DISCOVER_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[str]:
    """List AI Gateway language and evaluation model slugs. Never raises."""
    chat_url = vercel_chat_base_url(base_url)
    if not chat_url or not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(f"{chat_url}/models", headers=headers)
            response.raise_for_status()
            return vercel_model_ids(response.json())
    except (httpx.HTTPError, ValueError, OSError):
        return []


def vercel_model_ids(payload: object) -> list[str]:
    """Keep language and evaluation models; drop embeddings/media/rerankers."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return openai_compatible_model_ids(payload)
    names: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        model_type = str(item.get("type") or "language").strip().lower()
        if model_type in _NON_LANGUAGE_TYPES:
            continue
        names.append(model_id)
    return names


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
