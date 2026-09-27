"""End-to-end: harness tool calls drive a real Chromium page.

Skipped only when the Chromium binary is missing. CI installs it, so a launch
failure there fails the test instead of hiding it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from core_ai.providers.base import BaseProvider
from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent

from browser_agent.agent import BrowserAgent
from browser_agent.session import PlaywrightBrowser


PAGE_HTML = """<!doctype html><title>Example</title>
<form><input aria-label="Search" placeholder="Search"><button type="submit">Search</button></form>
<script>
document.querySelector("form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = document.querySelector("input").value.toLowerCase();
  document.body.insertAdjacentHTML("beforeend", query.includes("travel")
    ? "<p>The Alps Guide — $18 — A travel guide to alpine huts.</p>"
    : "<p>No matches.</p>");
});
</script>
"""


class ScriptedChat(BaseProvider):
    """Types, clicks, then answers once the price is on the page."""

    async def stream(self, model_name: str, messages: list[Message], tools: list[dict[str, Any]] = [], **kwargs: Any):
        del model_name, tools, kwargs
        text = messages[-1].content if isinstance(messages[-1].content, str) else ""
        if "$18" in text:
            yield StreamEvent(type="text_delta", delta="The Alps Guide costs $18.")
            yield StreamEvent(type="done")
            return
        if "travel" in text:
            yield StreamEvent(type="toolcall_start", tool_call_id="c-click", tool_name="click")
            yield StreamEvent(type="toolcall_delta", tool_call_id="c-click", delta=json.dumps({"index": 2}))
            yield StreamEvent(type="done")
            return
        yield StreamEvent(type="toolcall_start", tool_call_id="c-type", tool_name="type_text")
        yield StreamEvent(
            type="toolcall_delta",
            tool_call_id="c-type",
            delta=json.dumps({"index": 1, "text": "travel"}),
        )
        yield StreamEvent(type="done")


async def _run_page():
    browser = PlaywrightBrowser()
    try:
        await browser.start()
    except Exception as exc:
        await browser.stop()
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Chromium is not installed")
        raise
    registry = ModelRegistry()
    registry.register("fake", ScriptedChat())
    try:
        session = await browser.open("https://example.com")
        await session.page.set_content(PAGE_HTML)
        agent = BrowserAgent(registry=registry, model_id="fake:chat", max_steps=6)
        return await agent.run("Search for travel and report the price.", session)
    finally:
        await browser.stop()


def test_chromium_page_from_harness_tool_calls() -> None:
    result = asyncio.run(_run_page())
    assert result.status == "done", result.message
    assert result.output_text == "The Alps Guide costs $18."


def test_browser_refuses_non_http_urls() -> None:
    with pytest.raises(ValueError):
        asyncio.run(PlaywrightBrowser().open("data:text/html,<p>hi</p>"))
