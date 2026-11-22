"""An incomplete Responses stream still reports usage, then says why it stopped."""

import asyncio
from typing import List

import httpx

from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent

MESSAGES = [Message(role="user", content="Hi")]


def _sse(*frames: str) -> bytes:
    return "".join(f"data: {frame}\n\n" for frame in frames).encode()


def test_incomplete_response_reports_usage_and_reason() -> None:
    body = _sse(
        '{"type":"response.output_text.delta","delta":"Partial"}',
        '{"type":"response.incomplete","response":{"status":"incomplete",'
        '"incomplete_details":{"reason":"max_output_tokens"},"usage":{"input_tokens":40,'
        '"input_tokens_details":{"cached_tokens":0},"output_tokens":150,'
        '"output_tokens_details":{"reasoning_tokens":120},"total_tokens":190}}}',
    )
    provider = OpenAIProvider(
        api_key="test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
    )

    async def run() -> List[StreamEvent]:
        return [event async for event in provider.stream("gpt-6-luna", MESSAGES)]

    events = asyncio.run(run())
    assert [event.type for event in events] == ["text_delta", "usage", "incomplete", "done"]
    usage, incomplete = events[1], events[2]
    assert (usage.prompt_tokens, usage.completion_tokens, usage.reasoning_tokens) == (40, 150, 120)
    assert incomplete.incomplete_reason == "max_output_tokens"
