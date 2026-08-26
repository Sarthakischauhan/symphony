import base64
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from core_ai.content import split_text_and_images, to_openai_chat_content, to_openai_responses_content
from core_ai.models import get_model
from core_ai.providers.base import BaseProvider
from core_ai.providers.http import iter_sse_json, stream_with_retries
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)

_FORMAT_MEDIA = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


class OpenAIProvider(BaseProvider):
    """OpenAI chat-completions, responses, and image generation."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
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
        once = (
            self._stream_chat
            if self._uses_chat_completions(model_name)
            else self._stream_responses
        )
        async for event in stream_with_retries(
            lambda: once(model_name, messages, tools, max_output_tokens)
        ):
            yield event

    async def _stream_chat(
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
                async for data in iter_sse_json(response):
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

    async def _stream_responses(
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
                async for data in iter_sse_json(response):
                    event_type = data.get("type")
                    if event_type == "response.reasoning_summary_text.delta":
                        yield StreamEvent(
                            type="reasoning_delta",
                            content_index=data.get("summary_index", 0),
                            delta=data.get("delta", ""),
                        )
                    elif event_type == "response.output_text.delta":
                        yield StreamEvent(
                            type="text_delta",
                            content_index=data.get("content_index", 0),
                            delta=data.get("delta", ""),
                        )
                    elif event_type == "response.output_item.added":
                        item = data.get("item") or {}
                        if item.get("type") == "function_call":
                            item_id = str(item.get("id") or "")
                            index = int(data.get("output_index", 0))
                            tool_indexes[item_id] = index
                            tool_ids[item_id] = str(item.get("call_id") or item_id)
                            yield StreamEvent(
                                type="toolcall_start",
                                content_index=index,
                                tool_call_id=tool_ids[item_id],
                                tool_name=item.get("name"),
                            )
                    elif event_type == "response.function_call_arguments.delta":
                        item_id = str(data.get("item_id") or "")
                        yield StreamEvent(
                            type="toolcall_delta",
                            content_index=tool_indexes.get(item_id, int(data.get("output_index", 0))),
                            tool_call_id=tool_ids.get(item_id),
                            delta=data.get("delta", ""),
                        )
                    elif event_type == "response.completed":
                        usage = (data.get("response") or {}).get("usage") or {}
                        details = usage.get("output_tokens_details") or {}
                        yield StreamEvent(
                            type="usage",
                            prompt_tokens=usage.get("input_tokens"),
                            completion_tokens=usage.get("output_tokens"),
                            reasoning_tokens=details.get("reasoning_tokens"),
                            total_tokens=usage.get("total_tokens"),
                        )
                    elif event_type == "error":
                        raise RuntimeError(str(data.get("message") or "OpenAI stream error"))
        yield StreamEvent(type="done", content_index=0)

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        model = (
            model_name
            if model_name.startswith(("gpt-image", "dall-e"))
            else "gpt-image-1"
        )
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        if model.startswith("gpt-image"):
            body["output_format"] = output_format
        else:
            body["response_format"] = "b64_json"
        async with httpx.AsyncClient(transport=self.transport, timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error(response))
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("provider returned no image data")
        item = data[0] if isinstance(data[0], dict) else {}
        encoded = item.get("b64_json")
        media_type = _FORMAT_MEDIA.get(output_format, "image/png")
        if encoded:
            return base64.b64decode(encoded), media_type
        url = str(item.get("url") or "")
        if not url:
            raise RuntimeError("provider returned no image data")
        async with httpx.AsyncClient(transport=self.transport, timeout=120.0) as client:
            downloaded = await client.get(url)
            if downloaded.status_code >= 400:
                raise RuntimeError(_http_error(downloaded))
            return downloaded.content, media_type

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        model = get_model("openai", model_name)
        if model is not None:
            return model.api == "chat_completions"
        return model_name.startswith(("o1", "o3", "o4"))

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        return model_name.startswith(("gpt-5", "o1", "o3", "o4"))

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

    @staticmethod
    def _responses_input(messages: List[Message]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        pending_images: List[Dict[str, Any]] = []

        def flush_images() -> None:
            if not pending_images:
                return
            items.append(
                {
                    "role": "user",
                    "content": to_openai_responses_content(list(pending_images)),
                }
            )
            pending_images.clear()

        for message in messages:
            if message.role == "tool":
                text, images = split_text_and_images(message.content)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": text,
                    }
                )
                pending_images.extend(images)
                continue
            flush_images()
            if message.content:
                items.append(
                    {
                        "role": message.role,
                        "content": to_openai_responses_content(
                            message.content,
                            role=message.role,
                        ),
                    }
                )
            for tool_call in message.tool_calls or []:
                function = tool_call.get("function") or {}
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments", "{}"),
                    }
                )
        flush_images()
        return items


def _http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    return (response.text or "").strip() or f"HTTP {response.status_code}"
