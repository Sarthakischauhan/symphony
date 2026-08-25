import asyncio
import json
import os

import pytest
import httpx
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
from dotenv import load_dotenv

load_dotenv(override=True)


def test_gpt_5_6_uses_responses_reasoning_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert payload["max_output_tokens"] == 900
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"type":"response.reasoning_summary_text.delta","summary_index":0,"delta":"Checking files"}',
                '{"type":"response.output_text.delta","content_index":0,"delta":"Done"}',
                '{"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":7,"output_tokens_details":{"reasoning_tokens":4},"total_tokens":17}}}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(
            api_key="test",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "gpt-5.6-luna",
                [Message(role="user", content="Inspect it")],
                max_output_tokens=900,
            )
        ]

    events = asyncio.run(collect())
    assert [(event.type, event.delta) for event in events[:2]] == [
        ("reasoning_delta", "Checking files"),
        ("text_delta", "Done"),
    ]
    assert events[2].reasoning_tokens == 4
    assert events[-1].type == "done"


def test_legacy_reasoning_model_uses_completion_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["reasoning_effort"] == "medium"
        assert payload["max_completion_tokens"] == 900
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"choices":[{"index":0,"delta":{"content":"Done"}}]}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(
            api_key="test",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "o3",
                [Message(role="user", content="Inspect it")],
                max_output_tokens=900,
            )
        ]

    events = asyncio.run(collect())
    assert events[0].delta == "Done"
    assert events[-1].type == "done"


def test_regular_model_uses_responses_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"type":"response.output_text.delta","content_index":0,"delta":"Done"}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "gpt-4o-mini", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())
    assert events[0].delta == "Done"
    assert events[-1].type == "done"


def test_rate_limit_retries_using_retry_after_header() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        body = "\n\n".join(
            (
                'data: {"type":"response.output_text.delta","content_index":0,"delta":"Done"}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "gpt-5.6-luna", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())

    assert requests == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].retry_after == 0
    assert events[0].retry_attempt == 1
    assert events[1].delta == "Done"


def call_openai_provider(
    prompt: str = "what is 3+5. just answer in number",
    model_name: str | None = None,
) -> str:
    if os.getenv("RUN_LIVE_OPENAI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_OPENAI_TESTS=1 to run the OpenAI provider smoke test.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("Set OPENAI_API_KEY to run the OpenAI provider smoke test.")

    provider = OpenAIProvider(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    selected_model = model_name or os.getenv("OPENAI_TEST_MODEL", "gpt-4o-mini")
    messages = [Message(role="user", content=prompt)]

    return asyncio.run(_collect_text_and_usage(provider, selected_model, messages))


async def _collect_text_and_usage(
    provider: OpenAIProvider, model_name: str, messages: list[Message]
) -> str:
    chunks: list[str] = []
    usage = []
    async for event in provider.stream(model_name=model_name, messages=messages):
        if event.type == "text_delta" and event.delta:
            chunks.append(event.delta)
        if event.type == "usage":
            usage.append({
                "prompt_tokens": event.prompt_tokens,
                "total_tokens": event.total_tokens,
            })

    return ("".join(chunks).strip(), usage)


def test_openai_provider_smoke() -> None:
    response_text, _= call_openai_provider()
    assert response_text == "8"

def test_openai_provider_with_usage() -> None:
    response_text, usage = call_openai_provider("how many letters in word pizza ? just answer in number")
    assert response_text  == "5"

    assert usage is not None


def test_openai_chat_completions_sends_image_url_parts() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"choices":[{"index":0,"delta":{"content":"cat"}}]}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> None:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "o3",
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
    assert content[0] == {"type": "text", "text": "what is this?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aaa"


def test_openai_responses_sends_input_image_parts() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"type":"response.output_text.delta","content_index":0,"delta":"cat"}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> None:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream(
            "gpt-4o-mini",
            [
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "what is this?"},
                        {"type": "image", "media_type": "image/png", "data": "aaa"},
                    ],
                )
            ],
        ):
            pass

    asyncio.run(collect())
    content = captured["payload"]["input"][0]["content"]  # type: ignore[index]
    assert content[0] == {"type": "input_text", "text": "what is this?"}
    assert content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,aaa",
    }


def test_openai_forwards_tool_images_as_followup_user_content() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        if request.url.path.endswith("/chat/completions"):
            body = "\n\n".join(
                f"data: {event}"
                for event in (
                    '{"choices":[{"index":0,"delta":{"content":"cat"}}]}',
                    "[DONE]",
                )
            )
        else:
            body = "\n\n".join(
                f"data: {event}"
                for event in (
                    '{"type":"response.output_text.delta","content_index":0,"delta":"cat"}',
                    "[DONE]",
                )
            )
        return httpx.Response(200, text=body)

    tool_messages = [
        Message(role="user", content="look"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"shot.png"}'},
                }
            ],
        ),
        Message(
            role="tool",
            tool_call_id="call_1",
            content=[
                {"type": "text", "text": "Read image shot.png (image/png, 3 bytes)"},
                {"type": "image", "media_type": "image/png", "data": "aaa", "filename": "shot.png"},
            ],
        ),
    ]

    async def collect_chat() -> None:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream("o3", tool_messages):
            pass

    asyncio.run(collect_chat())
    messages = captured["payload"]["messages"]  # type: ignore[index]
    assert messages[-2]["role"] == "tool"
    assert "aaa" not in messages[-2]["content"]
    assert messages[-2]["content"].startswith("Read image shot.png")
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"][0]["type"] == "image_url"
    assert messages[-1]["content"][0]["image_url"]["url"] == "data:image/png;base64,aaa"

    async def collect_responses() -> None:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        async for _event in provider.stream("gpt-4o-mini", tool_messages):
            pass

    asyncio.run(collect_responses())
    items = captured["payload"]["input"]  # type: ignore[index]
    assert items[-2]["type"] == "function_call_output"
    assert "aaa" not in items[-2]["output"]
    assert items[-1]["role"] == "user"
    assert items[-1]["content"][0]["type"] == "input_image"


def test_openai_generate_image_uses_images_api() -> None:
    captured: dict[str, object] = {}
    png = "iVBORw0KGgo="

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": png}]})

    async def run() -> tuple[bytes, str]:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        return await provider.generate_image("gpt-4o", "a blue otter", "webp")

    payload, media_type = asyncio.run(run())
    assert captured["path"] == "/v1/images/generations"
    body = captured["payload"]
    assert body["model"] == "gpt-image-1"
    assert body["prompt"] == "a blue otter"
    assert body["output_format"] == "webp"
    assert media_type == "image/webp"
    assert payload == __import__("base64").b64decode(png)


def test_registry_falls_back_from_anthropic_to_openai_image_gen() -> None:
    png = "iVBORw0KGgo="

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": png}]})

    from core_ai.providers.anthropic import AnthropicProvider
    from core_ai.registry import ModelRegistry

    registry = ModelRegistry()
    registry.register("anthropic", AnthropicProvider(api_key="test"))
    registry.register(
        "openai",
        OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler)),
    )

    async def run() -> tuple[bytes, str]:
        return await registry.generate_image(
            "a cat", output_format="png", model_id="anthropic:claude-sonnet-5"
        )

    payload, media_type = asyncio.run(run())
    assert media_type == "image/png"
    assert payload == __import__("base64").b64decode(png)
