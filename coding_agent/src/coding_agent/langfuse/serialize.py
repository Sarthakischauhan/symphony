"""Serialize harness payloads for Langfuse without sending secrets or images."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from core_ai.content import text_from_content
from core_ai.types import Message

from coding_agent.learning.sanitize import redact_secrets

DEFAULT_MAX_CHARS = 32_000


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def serialize_content(content: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> Any:
    """Return text-only content; image parts become filename placeholders."""
    if content is None:
        return ""
    if isinstance(content, str):
        return _truncate(redact_secrets(content), max_chars)
    try:
        return _truncate(redact_secrets(text_from_content(content)), max_chars)
    except Exception:
        return _truncate(redact_secrets(str(content)), max_chars)


def serialize_message(message: Message, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    """Dump one conversation message as it would be sent to the model."""
    payload: dict[str, Any] = {
        "role": message.role,
        "content": serialize_content(message.content, max_chars=max_chars),
    }
    if message.tool_calls:
        payload["tool_calls"] = _redact(message.tool_calls)
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def serialize_messages(
    messages: Iterable[Any],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, Message):
            serialized.append(serialize_message(message, max_chars=max_chars))
        else:
            serialized.append({"role": "unknown", "content": serialize_content(message, max_chars=max_chars)})
    return serialized


def serialize_tool_result(result: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    content = getattr(result, "content", result)
    payload: dict[str, Any] = {
        "status": getattr(result, "status", None),
        "content": serialize_content(content, max_chars=max_chars),
    }
    error_type = getattr(result, "error_type", None)
    if error_type:
        payload["error_type"] = error_type
    return payload


def usage_payload(usage: Any) -> Optional[dict[str, int]]:
    if usage is None:
        return None
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        data = dump()
        return {
            "input": int(data.get("prompt_tokens") or 0),
            "output": int(data.get("completion_tokens") or 0),
            "total": int(data.get("total_tokens") or 0),
        }
    return None
