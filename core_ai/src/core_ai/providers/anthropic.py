import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx
from dotenv import load_dotenv

from core_ai.content import to_anthropic_blocks
from core_ai.providers.base import BaseProvider
from core_ai.providers.http import iter_sse_json, stream_with_retries
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)

DEFAULT_MAX_TOKENS = 8192
Content = Union[str, List[Dict[str, Any]]]


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API streaming provider."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        transport: Optional[httpx.AsyncBaseTransport] = None,
        api_version: str = "2023-06-01",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.api_version = api_version

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        del reasoning_effort
        async for event in stream_with_retries(
            lambda: self._stream_once(
                model_name,
                messages,
                tools,
                max_output_tokens=max_output_tokens,
            )
        ):
            yield event

    async def _stream_once(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        system, payload_messages = self._messages_payload(messages)
        payload: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_output_tokens or DEFAULT_MAX_TOKENS,
            "stream": True,
            "messages": payload_messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("parameters") or {"type": "object", "properties": {}},
                }
                for tool in tools
            ]

        async with httpx.AsyncClient(transport=self.transport) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=self._headers,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for data in iter_sse_json(response):
                    event = self._translate(data)
                    if event is not None:
                        yield event
        yield StreamEvent(type="done", content_index=0)

    def _translate(self, data: Dict[str, Any]) -> Optional[StreamEvent]:
        event_type = data.get("type")
        if event_type == "content_block_start":
            block = data.get("content_block") or {}
            index = int(data.get("index") or 0)
            if block.get("type") == "tool_use":
                return StreamEvent(
                    type="toolcall_start",
                    content_index=index,
                    tool_call_id=block.get("id"),
                    tool_name=block.get("name"),
                )
            return None
        if event_type == "content_block_delta":
            delta = data.get("delta") or {}
            index = int(data.get("index") or 0)
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                return StreamEvent(
                    type="text_delta",
                    content_index=index,
                    delta=delta.get("text") or "",
                )
            if delta_type == "thinking_delta":
                return StreamEvent(
                    type="reasoning_delta",
                    content_index=index,
                    delta=delta.get("thinking") or "",
                )
            if delta_type == "input_json_delta":
                return StreamEvent(
                    type="toolcall_delta",
                    content_index=index,
                    delta=delta.get("partial_json") or "",
                )
            return None
        if event_type == "message_delta":
            usage = data.get("usage") or {}
            if "output_tokens" in usage:
                return StreamEvent(
                    type="usage",
                    completion_tokens=usage.get("output_tokens"),
                )
            return None
        if event_type == "message_start":
            usage = (data.get("message") or {}).get("usage") or {}
            if "input_tokens" in usage:
                return StreamEvent(
                    type="usage",
                    prompt_tokens=usage.get("input_tokens"),
                )
            return None
        return None

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    @classmethod
    def _messages_payload(cls, messages: List[Message]) -> tuple[str, List[Dict[str, Any]]]:
        system_chunks: List[str] = []
        items: List[Dict[str, Any]] = []
        pending_tool_results: List[Dict[str, Any]] = []

        def flush_tool_results() -> None:
            if pending_tool_results:
                cls._append_role(items, "user", list(pending_tool_results))
                pending_tool_results.clear()

        for message in messages:
            if message.role == "system":
                flush_tool_results()
                if isinstance(message.content, str) and message.content:
                    system_chunks.append(message.content)
                continue
            if message.role == "tool":
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": (
                            message.content
                            if isinstance(message.content, str)
                            else to_anthropic_blocks(message.content)
                        ),
                    }
                )
                continue
            flush_tool_results()
            if message.role == "assistant":
                content: List[Dict[str, Any]] = to_anthropic_blocks(message.content)
                for tool_call in message.tool_calls or []:
                    function = tool_call.get("function") or {}
                    raw_args = function.get("arguments") or "{}"
                    try:
                        parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        parsed = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.get("id"),
                            "name": function.get("name"),
                            "input": parsed if isinstance(parsed, dict) else {},
                        }
                    )
                if content:
                    cls._append_role(items, "assistant", content)
                continue
            cls._append_role(items, "user", to_anthropic_blocks(message.content))
        flush_tool_results()
        return "\n\n".join(system_chunks), items

    @staticmethod
    def _append_role(items: List[Dict[str, Any]], role: str, content: Content) -> None:
        if items and items[-1]["role"] == role:
            items[-1]["content"] = AnthropicProvider._merge_content(
                items[-1]["content"],
                content,
            )
            return
        items.append({"role": role, "content": content})

    @staticmethod
    def _merge_content(left: Content, right: Content) -> List[Dict[str, Any]]:
        return AnthropicProvider._as_blocks(left) + AnthropicProvider._as_blocks(right)

    @staticmethod
    def _as_blocks(content: Content) -> List[Dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        return list(content)
