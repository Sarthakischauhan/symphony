import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from core_ai.providers.base import BaseProvider
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:

        # 1. Format the raw HTTP JSON payload
        payload = {
            "model": model_name,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [],
        }

        for message in messages:
            formatted = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                formatted["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                formatted["tool_calls"] = message.tool_calls
            payload["messages"].append(formatted)

        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

        # 2. Open the TCP connection directly
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            ) as response:
                response.raise_for_status()

                # 3. Manually parse the SSE lines and buffers
                async for line in response.aiter_lines():
                    line = line.strip()

                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Strip the "data: " prefix

                    if data_str == "[DONE]":
                        break  # OpenAI signals stream termination

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue  # Ignore malformed stream breaks

                    usage = chunk.get("usage")
                    if usage:
                        yield StreamEvent(
                            type="usage",
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=usage.get("completion_tokens"),
                            total_tokens=usage.get("total_tokens"),
                        )

                    if not chunk.get("choices"):
                        continue

                    delta = chunk["choices"][0].get("delta", {})
                    index = chunk["choices"][0].get("index", 0)

                    # --- Text Delta Extraction ---
                    if "content" in delta and delta["content"] is not None:
                        yield StreamEvent(
                            type="text_delta",
                            content_index=index,
                            delta=delta["content"],
                        )

                    # --- Tool Call Extraction ---
                    if "tool_calls" in delta:
                        for t_call in delta["tool_calls"]:
                            t_idx = t_call.get("index", 0)
                            func = t_call.get("function", {})

                            # Tool execution start
                            if "name" in func:
                                yield StreamEvent(
                                    type="toolcall_start",
                                    content_index=t_idx,
                                    tool_call_id=t_call.get("id"),
                                    tool_name=func["name"],
                                )

                            # Streaming JSON argument chunks
                            if "arguments" in func:
                                yield StreamEvent(
                                    type="toolcall_delta",
                                    content_index=t_idx,
                                    delta=func["arguments"],
                                )

        yield StreamEvent(type="done", content_index=0)
