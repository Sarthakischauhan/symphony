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


def _jsonish(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except TypeError:
            pass
    return value


def _redact(value: Any) -> Any:
    value = _jsonish(value)
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return redact_secrets(str(value))


def _truncate_value(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return _truncate(value, max_chars)
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars) for item in value]
    if isinstance(value, tuple):
        return [_truncate_value(item, max_chars) for item in value]
    return value


def _sanitize(value: Any, max_chars: int) -> Any:
    return _truncate_value(_redact(value), max_chars)


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


def serialize_task(task: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Bound, redacted run input (the user task text)."""
    return serialize_content(task, max_chars=max_chars)


def serialize_run_output(output: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Bound, redacted final run output (``output_text`` or the original task)."""
    return serialize_content(output, max_chars=max_chars)


def serialize_tool_arguments(arguments: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> Any:
    """Redact and bound tool-call arguments before they leave the process."""
    if arguments is None:
        return {}
    return _sanitize(arguments, max_chars)


def serialize_turn_output(
    text: Any = "",
    tool_calls: Any = None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Bound, redacted generation output: assistant text plus any tool calls."""
    payload: dict[str, Any] = {"text": serialize_content(text, max_chars=max_chars)}
    if tool_calls:
        payload["tool_calls"] = serialize_tool_arguments(tool_calls, max_chars=max_chars)
    return payload


def serialize_message(message: Message, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    """Dump one conversation message as it would be sent to the model."""
    payload: dict[str, Any] = {
        "role": message.role,
        "content": serialize_content(message.content, max_chars=max_chars),
    }
    if message.tool_calls:
        payload["tool_calls"] = serialize_tool_arguments(message.tool_calls, max_chars=max_chars)
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
