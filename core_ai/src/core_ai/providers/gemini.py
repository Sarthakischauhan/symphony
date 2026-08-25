import base64
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from core_ai.content import split_text_and_images, to_gemini_parts
from core_ai.providers.base import BaseProvider
from core_ai.providers.http import iter_sse_json, stream_with_retries
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)


class GeminiProvider(BaseProvider):
    """Google Gemini generateContent streaming provider."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
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
        async for event in stream_with_retries(
            lambda: self._stream_once(
                model_name,
                messages,
                tools,
                max_output_tokens=max_output_tokens,
            )
        ):
            yield event

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        del output_format
        model_id = model_name.removeprefix("models/")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/models/{model_id}:generateContent",
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error(response))
            body = response.json()
        return _first_inline_image(body)

    async def _stream_once(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        system, contents = self._contents_payload(messages)
        payload: Dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters")
                            or {"type": "object", "properties": {}},
                        }
                        for tool in tools
                    ]
                }
            ]
        if max_output_tokens is not None:
            payload["generationConfig"] = {"maxOutputTokens": max_output_tokens}

        model_id = model_name.removeprefix("models/")
        tool_index = 0
        latest_usage: Optional[StreamEvent] = None
        async with httpx.AsyncClient(transport=self.transport) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/models/{model_id}:streamGenerateContent",
                params={"alt": "sse"},
                json=payload,
                headers=self._headers,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for data in iter_sse_json(response):
                    events, tool_index = self._translate(data, tool_index)
                    for event in events:
                        if event.type == "usage":
                            latest_usage = event
                            continue
                        yield event
        if latest_usage is not None:
            yield latest_usage
        yield StreamEvent(type="done", content_index=0)

    def _translate(
        self, data: Dict[str, Any], tool_index: int
    ) -> tuple[List[StreamEvent], int]:
        events: List[StreamEvent] = []
        prompt_feedback = data.get("promptFeedback") or {}
        if prompt_feedback.get("blockReason"):
            raise RuntimeError(
                str(prompt_feedback.get("blockReason") or "Gemini blocked the prompt")
            )
        for candidate in data.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if part.get("thought") and part.get("text"):
                    events.append(
                        StreamEvent(
                            type="reasoning_delta",
                            content_index=0,
                            delta=part["text"],
                        )
                    )
                    continue
                if part.get("text"):
                    events.append(
                        StreamEvent(
                            type="text_delta",
                            content_index=0,
                            delta=part["text"],
                        )
                    )
                    continue
                function_call = part.get("functionCall")
                if function_call:
                    events.append(
                        StreamEvent(
                            type="toolcall_start",
                            content_index=tool_index,
                            tool_call_id=f"gemini-tool-{tool_index}",
                            tool_name=function_call.get("name"),
                        )
                    )
                    args = function_call.get("args")
                    if args:
                        events.append(
                            StreamEvent(
                                type="toolcall_delta",
                                content_index=tool_index,
                                delta=json.dumps(args, separators=(",", ":")),
                            )
                        )
                    tool_index += 1
        usage = data.get("usageMetadata") or {}
        if usage:
            events.append(
                StreamEvent(
                    type="usage",
                    prompt_tokens=usage.get("promptTokenCount"),
                    completion_tokens=usage.get("candidatesTokenCount"),
                    reasoning_tokens=usage.get("thoughtsTokenCount"),
                    total_tokens=usage.get("totalTokenCount"),
                )
            )
        return events, tool_index

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _contents_payload(messages: List[Message]) -> tuple[str, List[Dict[str, Any]]]:
        system_chunks: List[str] = []
        contents: List[Dict[str, Any]] = []
        pending_responses: List[Dict[str, Any]] = []
        call_names: Dict[str, str] = {}

        def flush_tool_responses() -> None:
            if pending_responses:
                contents.append({"role": "user", "parts": list(pending_responses)})
                pending_responses.clear()

        for message in messages:
            if message.role == "system":
                flush_tool_responses()
                if isinstance(message.content, str) and message.content:
                    system_chunks.append(message.content)
                continue
            if message.role == "tool":
                name = call_names.get(str(message.tool_call_id or ""), "tool")
                text, images = split_text_and_images(message.content)
                pending_responses.append(
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": text},
                        }
                    }
                )
                pending_responses.extend(to_gemini_parts(images))
                continue
            flush_tool_responses()
            if message.role == "assistant":
                parts: List[Dict[str, Any]] = to_gemini_parts(message.content)
                for tool_call in message.tool_calls or []:
                    function = tool_call.get("function") or {}
                    raw_args = function.get("arguments") or "{}"
                    try:
                        parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        parsed = {}
                    name = function.get("name")
                    call_id = tool_call.get("id")
                    if call_id and name:
                        call_names[str(call_id)] = str(name)
                    parts.append(
                        {
                            "functionCall": {
                                "name": name,
                                "args": parsed if isinstance(parsed, dict) else {},
                            }
                        }
                    )
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue
            parts = to_gemini_parts(message.content)
            if parts:
                contents.append({"role": "user", "parts": parts})
        flush_tool_responses()
        return "\n\n".join(system_chunks), contents


def _first_inline_image(payload: Dict[str, Any]) -> tuple[bytes, str]:
    for candidate in payload.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            data = inline.get("data")
            if not data:
                continue
            media_type = str(
                inline.get("mimeType") or inline.get("mime_type") or "image/png"
            )
            return base64.b64decode(data), media_type
    raise RuntimeError("provider returned no image data")


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
