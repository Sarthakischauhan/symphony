import asyncio
import json

import httpx

from core_ai.providers.gemini import GeminiProvider
from core_ai.types import Message, StreamEvent


def _sse(*events: str) -> str:
    return "\n\n".join(f"data: {event}" for event in events) + "\n\n"


def test_gemini_streams_reasoning_text_tools_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models/gemini-3.7-flash:streamGenerateContent")
        assert request.url.params["alt"] == "sse"
        assert request.headers["x-goog-api-key"] == "test"
        payload = json.loads(request.content)
        assert payload["systemInstruction"]["parts"][0]["text"] == "Be brief"
        assert payload["generationConfig"]["maxOutputTokens"] == 900
        assert payload["tools"][0]["functionDeclarations"][0]["name"] == "read_file"
        body = _sse(
            '{"candidates":[{"content":{"parts":[{"text":"Checking","thought":true}]}}]}',
            '{"candidates":[{"content":{"parts":[{"text":"Done"},{"functionCall":{"name":"read_file","args":{"path":"a.py"}}}]}}],"usageMetadata":{"promptTokenCount":9,"candidatesTokenCount":4,"thoughtsTokenCount":2,"totalTokenCount":15}}',
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = GeminiProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "models/gemini-3.7-flash",
                [
                    Message(role="system", content="Be brief"),
                    Message(role="user", content="Read a.py"),
                ],
                tools=[{"name": "read_file", "description": "Read a file", "parameters": {"type": "object"}}],
                max_output_tokens=900,
            )
        ]

    events = asyncio.run(collect())
    assert [event.type for event in events] == [
        "reasoning_delta",
        "text_delta",
        "toolcall_start",
        "toolcall_delta",
        "usage",
        "done",
    ]
    assert events[0].delta == "Checking"
    assert events[1].delta == "Done"
    assert events[2].tool_name == "read_file"
    assert events[3].delta == '{"path":"a.py"}'
    assert events[4].total_tokens == 15
    assert events[4].reasoning_tokens == 2


def test_gemini_rate_limit_retries_using_retry_after_header() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            text=_sse('{"candidates":[{"content":{"parts":[{"text":"Done"}]}}]}'),
        )

    async def collect() -> list[StreamEvent]:
        provider = GeminiProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "gemini-3.7-flash", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())
    assert requests == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[1].delta == "Done"


def test_gemini_translates_tool_history() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse('{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'),
        )

    async def collect() -> None:
        provider = GeminiProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "gemini-3.7-flash",
            [
                Message(role="user", content="edit it"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                        }
                    ],
                ),
                Message(role="tool", content="print(1)", tool_call_id="call_1"),
            ],
        ):
            pass

    asyncio.run(collect())
    contents = captured["payload"]["contents"]  # type: ignore[index]
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "read_file"
    assert contents[2]["role"] == "user"
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "read_file"
    assert contents[2]["parts"][0]["functionResponse"]["response"]["result"] == "print(1)"


def test_gemini_attaches_tool_images_next_to_function_response() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse('{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'),
        )

    async def collect() -> None:
        provider = GeminiProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "gemini-3.7-flash",
            [
                Message(role="user", content="look"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"shot.gif"}'},
                        }
                    ],
                ),
                Message(
                    role="tool",
                    tool_call_id="call_1",
                    content=[
                        {"type": "text", "text": "Read image shot.gif"},
                        {"type": "image", "media_type": "image/gif", "data": "aaa", "filename": "shot.gif"},
                    ],
                ),
            ],
        ):
            pass

    asyncio.run(collect())
    parts = captured["payload"]["contents"][2]["parts"]  # type: ignore[index]
    assert parts[0]["functionResponse"]["response"]["result"] == "Read image shot.gif"
    assert "aaa" not in parts[0]["functionResponse"]["response"]["result"]
    assert parts[1] == {"inlineData": {"mimeType": "image/gif", "data": "aaa"}}


def test_gemini_sends_inline_image_parts() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse('{"candidates":[{"content":{"parts":[{"text":"cat"}]}}]}'),
        )

    async def collect() -> None:
        provider = GeminiProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "gemini-3.7-flash",
            [
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "what is this?"},
                        {"type": "image", "media_type": "image/png", "data": "aaa", "filename": "shot.png"},
                    ],
                )
            ],
        ):
            pass

    asyncio.run(collect())
    parts = captured["payload"]["contents"][0]["parts"]  # type: ignore[index]
    assert parts == [
        {"text": "what is this?"},
        {"inlineData": {"mimeType": "image/png", "data": "aaa"}},
    ]
