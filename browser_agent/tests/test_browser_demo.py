"""End-to-end: evaluation answers drive a real Chromium page.

Skipped only when the Chromium binary is missing. CI installs it, so a launch
failure there fails the test instead of hiding it.
"""

from __future__ import annotations

import asyncio

import pytest
from fakes import ScriptedJev

from browser_agent.agent import BrowserAgent
from browser_agent.demo_site import DEMO_GOAL, DemoSite
from browser_agent.jev_policy import JevPolicy
from browser_agent.session import PlaywrightBrowser


async def _run_catalog():
    browser = PlaywrightBrowser()
    try:
        await browser.start()
    except Exception as exc:
        await browser.stop()
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Chromium is not installed")
        raise
    site = DemoSite()
    try:
        session = await browser.open(site.url)
        agent = BrowserAgent(JevPolicy(ScriptedJev(), model="typesafe-ai/jev", provider="vercel"), max_steps=6)
        return await agent.run(DEMO_GOAL, session)
    finally:
        await browser.stop()
        site.close()


def test_chromium_catalog_from_jev_answers() -> None:
    result = asyncio.run(_run_catalog())
    assert result.status == "done", result.message
    assert "$18" in result.output_text
    assert "Alps Guide" in result.output_text
    assert [step.operation for step in result.steps] == ["TYPE_TEXT", "CLICK", "DONE"]


def test_browser_refuses_non_http_urls() -> None:
    with pytest.raises(ValueError):
        asyncio.run(PlaywrightBrowser().open("data:text/html,<p>hi</p>"))
