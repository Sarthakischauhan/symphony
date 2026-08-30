import asyncio
import json

import httpx
import pytest

from core_ai.providers.anthropic import AnthropicProvider
from core_ai.types import Message, StreamEvent


def _sse(*events: str) -> str:
    return "\n\n".join(f"data: {event}" for event in events) + "\n\n"


def test_anthropic_streams_text_tools_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test"
        payload = json.loads(request.content)
        assert payload["model"] == "claude-sonnet-5"
        assert payload["max_tokens"] == 900
        assert payload["system"] == "Be brief"
        assert payload["tools"][0]["name"] == "read_file"
        assert payload["tools"][0]["input_schema"]["type"] == "object"
        assert payload["messages"][0]["role"] == "user"
        body = _sse(
            '{"type":"message_start","message":{"usage":{"input_tokens":11}}}',
            '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
            '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Reading"}}',
            '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Need the file"}}',
            '{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"read_file"}}',
            '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"a.py\\"}"}}',
            '{"type":"message_delta","usage":{"output_tokens":7}}',
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "claude-sonnet-5",
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
        "usage",
        "text_delta",
        "reasoning_delta",
        "toolcall_start",
        "toolcall_delta",
        "usage",
        "done",
    ]
    assert events[0].prompt_tokens == 11
    assert events[1].delta == "Reading"
    assert events[2].delta == "Need the file"
    assert events[3].tool_name == "read_file"
    assert events[3].tool_call_id == "toolu_1"
    assert events[4].delta == '{"path":"a.py"}'
    assert events[5].completion_tokens == 7


def test_anthropic_rate_limit_retries_using_retry_after_header() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Done"}}'
            ),
        )

    async def collect() -> list[StreamEvent]:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "claude-sonnet-5", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())
    assert requests == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].retry_after == 0
    assert events[1].delta == "Done"


def test_anthropic_retries_retryable_in_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(
                200,
                text=_sse(
                    '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
                ),
            )
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Done"}}'
            ),
        )

    monkeypatch.setattr("core_ai.providers.http.asyncio.sleep", no_sleep)

    async def collect() -> list[StreamEvent]:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "claude-sonnet-5", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())

    assert requests == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].retry_reason == "stream_error"
    assert events[1].delta == "Done"


def test_anthropic_does_not_retry_terminal_in_stream_error() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"error","error":{"type":"invalid_request_error","message":"Bad request"}}'
            ),
        )

    async def collect() -> None:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "claude-sonnet-5", [Message(role="user", content="Do it")]
        ):
            pass

    with pytest.raises(RuntimeError, match="Bad request"):
        asyncio.run(collect())
    assert requests == 1


def test_anthropic_translates_tool_history() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}'
            ),
        )

    async def collect() -> None:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "claude-sonnet-5",
            [
                Message(role="user", content="edit it"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                        }
                    ],
                ),
                Message(role="tool", content="print(1)", tool_call_id="toolu_1"),
            ],
        ):
            pass

    asyncio.run(collect())
    messages = captured["payload"]["messages"]  # type: ignore[index]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[1]["content"][0]["input"] == {"path": "a.py"}
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["type"] == "tool_result"
    assert messages[2]["content"][0]["tool_use_id"] == "toolu_1"


def test_anthropic_puts_tool_images_in_tool_result_blocks() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}'
            ),
        )

    async def collect() -> None:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "claude-sonnet-5",
            [
                Message(role="user", content="look"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"shot.png"}'},
                        }
                    ],
                ),
                Message(
                    role="tool",
                    tool_call_id="toolu_1",
                    content=[
                        {"type": "text", "text": "Read image shot.png"},
                        {"type": "image", "media_type": "image/png", "data": "aaa", "filename": "shot.png"},
                    ],
                ),
            ],
        ):
            pass

    asyncio.run(collect())
    result = captured["payload"]["messages"][2]["content"][0]  # type: ignore[index]
    assert result["type"] == "tool_result"
    assert result["content"][0] == {"type": "text", "text": "Read image shot.png"}
    assert result["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "aaa"},
    }


def test_anthropic_merges_consecutive_same_role_messages() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}'
            ),
        )

    async def collect() -> None:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "claude-sonnet-5",
            [
                Message(role="user", content="first"),
                Message(role="user", content="second"),
            ],
        ):
            pass

    asyncio.run(collect())
    messages = captured["payload"]["messages"]  # type: ignore[index]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]


def test_anthropic_sends_image_blocks() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse(
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"cat"}}'
            ),
        )

    async def collect() -> None:
        provider = AnthropicProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "claude-sonnet-5",
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
    content = captured["payload"]["messages"][0]["content"]  # type: ignore[index]
    assert content == [
        {"type": "text", "text": "what is this?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aaa"}},
    ]


def test_anthropic_does_not_generate_images() -> None:
    provider = AnthropicProvider(api_key="test")

    async def run() -> None:
        await provider.generate_image("claude-sonnet-5", "a cat")

    try:
        asyncio.run(run())
    except NotImplementedError as exc:
        assert "does not support image generation" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError")
