"""OpenAI reasoning params follow the catalog's reasoning flag and effort levels."""

import asyncio
import json
from typing import List, Optional

import httpx
import pytest

from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message

MESSAGES = [Message(role="user", content="Hi")]


def _sse(*frames: str) -> bytes:
    return "".join(f"data: {frame}\n\n" for frame in frames).encode()


def _payload(model: str, effort: Optional[str]) -> dict:
    sent: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=_sse("[DONE]"))

    provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))

    async def run() -> None:
        async for _ in provider.stream(model, MESSAGES, reasoning_effort=effort):
            pass

    asyncio.run(run())
    return sent[0]


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        ("low", {"summary": "detailed", "effort": "low"}),
        ("none", {"summary": "detailed", "effort": "none"}),
        ("off", {"summary": "detailed", "effort": "none"}),
        (None, {"summary": "detailed", "effort": "medium"}),
        ("minimal", {"summary": "detailed"}),
    ],
)
def test_responses_reasoning_follows_the_catalog_levels(effort: Optional[str], expected: dict) -> None:
    # gpt-6-luna has no gpt-5 prefix; the catalog marks it as a reasoning model.
    assert _payload("gpt-6-luna", effort)["reasoning"] == expected


def test_responses_model_outside_the_catalog_gets_no_reasoning_param() -> None:
    assert "reasoning" not in _payload("gpt-4o-mini", "low")


@pytest.mark.parametrize(("effort", "expected"), [("high", "high"), (None, "medium")])
def test_chat_reasoning_effort_uses_the_catalog_value(effort: Optional[str], expected: str) -> None:
    assert _payload("o4-mini", effort)["reasoning_effort"] == expected


def test_chat_effort_the_model_does_not_take_is_left_out() -> None:
    # o4-mini maps "off" to no provider value.
    assert "reasoning_effort" not in _payload("o4-mini", "off")
