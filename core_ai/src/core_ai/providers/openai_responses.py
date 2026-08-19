import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.providers.base import BaseProvider
from core_ai.types import Message, StreamEvent


class OpenAIResponsesProvider(BaseProvider):
    """OpenAI Responses API streaming provider."""

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
            "input": self._responses_input(messages),
        }
        if model_name.startswith("gpt-5"):
            payload["reasoning"] = {"effort": "medium", "summary": "auto"}
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if tools:
            payload["tools"] = [{"type": "function", **tool} for tool in tools]

        tool_indexes: Dict[str, int] = {}
        tool_ids: Dict[str, str] = {}
        async with httpx.AsyncClient(transport=self.transport) as client:
            async with client.stream(
                "POST", f"{self.base_url}/responses", json=payload,
                headers=self._headers, timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for data in self._sse_json(response):
                    event_type = data.get("type")
                    if event_type == "response.reasoning_summary_text.delta":
                        yield StreamEvent(
                            type="reasoning_delta",
                            content_index=data.get("summary_index", 0),
                            delta=data.get("delta", ""),
                        )
                    elif event_type == "response.output_text.delta":
                        yield StreamEvent(type="text_delta", content_index=data.get("content_index", 0), delta=data.get("delta", ""))
                    elif event_type == "response.output_item.added":
                        item = data.get("item") or {}
                        if item.get("type") == "function_call":
                            item_id = str(item.get("id") or "")
                            index = int(data.get("output_index", 0))
                            tool_indexes[item_id] = index
                            tool_ids[item_id] = str(item.get("call_id") or item_id)
                            yield StreamEvent(type="toolcall_start", content_index=index, tool_call_id=tool_ids[item_id], tool_name=item.get("name"))
                    elif event_type == "response.function_call_arguments.delta":
                        item_id = str(data.get("item_id") or "")
                        yield StreamEvent(type="toolcall_delta", content_index=tool_indexes.get(item_id, int(data.get("output_index", 0))), tool_call_id=tool_ids.get(item_id), delta=data.get("delta", ""))
                    elif event_type == "response.completed":
                        usage = (data.get("response") or {}).get("usage") or {}
                        details = usage.get("output_tokens_details") or {}
                        yield StreamEvent(type="usage", prompt_tokens=usage.get("input_tokens"), completion_tokens=usage.get("output_tokens"), reasoning_tokens=details.get("reasoning_tokens"), total_tokens=usage.get("total_tokens"))
                    elif event_type == "error":
                        raise RuntimeError(str(data.get("message") or "OpenAI stream error"))
        yield StreamEvent(type="done", content_index=0)

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream", "Content-Type": "application/json"}

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

    @staticmethod
    def _responses_input(messages: List[Message]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                items.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content})
                continue
            if message.content:
                items.append({"role": message.role, "content": message.content})
            for tool_call in message.tool_calls or []:
                function = tool_call.get("function") or {}
                items.append({"type": "function_call", "call_id": tool_call.get("id"), "name": function.get("name"), "arguments": function.get("arguments", "{}")})
        return items
