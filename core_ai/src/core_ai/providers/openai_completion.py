import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.content import split_text_and_images, to_openai_chat_content
from core_ai.providers.base import BaseProvider
from core_ai.types import Message, StreamEvent


class OpenAICompletionProvider(BaseProvider):
    """OpenAI Chat Completions streaming provider."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        payload: Dict[str, Any] = {
            "model": model_name,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": self._chat_messages(messages),
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        if max_output_tokens is not None:
            payload["max_completion_tokens"] = max_output_tokens
        if self._is_reasoning_model(model_name):
            payload["reasoning_effort"] = "medium"

        async with httpx.AsyncClient(transport=self.transport) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for data in self._sse_json(response):
                    usage = data.get("usage")
                    if usage:
                        details = usage.get("completion_tokens_details") or {}
                        yield StreamEvent(
                            type="usage",
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=usage.get("completion_tokens"),
                            reasoning_tokens=details.get("reasoning_tokens"),
                            total_tokens=usage.get("total_tokens"),
                        )
                    if not data.get("choices"):
                        continue
                    delta = data["choices"][0].get("delta", {})
                    index = data["choices"][0].get("index", 0)
                    if delta.get("content") is not None:
                        yield StreamEvent(type="text_delta", content_index=index, delta=delta["content"])
                    for tool_call in delta.get("tool_calls", []):
                        tool_index = tool_call.get("index", 0)
                        function = tool_call.get("function", {})
                        if "name" in function:
                            yield StreamEvent(
                                type="toolcall_start",
                                content_index=tool_index,
                                tool_call_id=tool_call.get("id"),
                                tool_name=function["name"],
                            )
                        if "arguments" in function:
                            yield StreamEvent(
                                type="toolcall_delta",
                                content_index=tool_index,
                                delta=function["arguments"],
                            )
        yield StreamEvent(type="done", content_index=0)

    @staticmethod
    def _chat_messages(messages: List[Message]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        pending_images: List[Dict[str, Any]] = []

        def flush_images() -> None:
            if not pending_images:
                return
            items.append(
                {
                    "role": "user",
                    "content": to_openai_chat_content(list(pending_images)),
                }
            )
            pending_images.clear()

        for message in messages:
            if message.role == "tool":
                text, images = split_text_and_images(message.content)
                formatted: Dict[str, Any] = {"role": "tool", "content": text}
                if message.tool_call_id:
                    formatted["tool_call_id"] = message.tool_call_id
                items.append(formatted)
                pending_images.extend(images)
                continue
            flush_images()
            formatted = {
                "role": message.role,
                "content": to_openai_chat_content(message.content),
            }
            if message.tool_call_id:
                formatted["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                formatted["tool_calls"] = message.tool_calls
            items.append(formatted)
        flush_images()
        return items

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        return model_name.startswith(("gpt-5", "o1", "o3", "o4"))

    @staticmethod
    async def _sse_json(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
        async for line in response.aiter_lines():
            line = line.strip()
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data
