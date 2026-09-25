"""End-to-end: evaluation answers drive a real Chromium page.

Skipped when Playwright cannot launch Chromium (CI does not download a browser).
"""

from __future__ import annotations

import pytest

from browser_agent.agent import BrowserAgent
from browser_agent.demo_site import DEMO_GOAL, DemoSite
from browser_agent.policy import JevPolicy
from browser_agent.session import PlaywrightBrowser


class CatalogJev:
    async def complete(self, state: dict, questions: dict) -> dict:
        del questions
        if "$18" in state["page_text"]:
            return {
                "model": "typesafe-ai/jev",
                "answers": {
                    "operation": {"type": "choice", "choice": "DONE", "probabilities": {"DONE": 0.97}},
                    "goal_met": {"type": "boolean", "probability": 0.96},
                },
            }
        elements = state["elements"]
        field = next((element for element in elements if element["kind"] == "type"), None)
        if field is not None and not field.get("value"):
            return {
                "model": "typesafe-ai/jev",
                "answers": {
                    "operation": {"type": "choice", "choice": "TYPE_TEXT", "probabilities": {"TYPE_TEXT": 0.94}},
                    "type_target": {"type": "choice", "choice": str(field["index"])},
                    "type_value": {"type": "choice", "choice": "travel", "probabilities": {"travel": 0.99}},
                    "goal_met": {"type": "boolean", "probability": 0.02},
                },
            }
        button = next(element for element in elements if element["kind"] == "click" and "search" in element["name"].lower())
        return {
            "model": "typesafe-ai/jev",
            "answers": {
                "operation": {"type": "choice", "choice": "CLICK", "probabilities": {"CLICK": 0.92}},
                "click_target": {"type": "choice", "choice": str(button["index"])},
                "goal_met": {"type": "boolean", "probability": 0.05},
            },
        }


async def _chromium_launches() -> bool:
    browser = PlaywrightBrowser()
    try:
        await browser.start()
    except Exception:
        return False
    await browser.stop()
    return True


@pytest.mark.asyncio
async def test_chromium_catalog_from_jev_answers() -> None:
    if not await _chromium_launches():
        pytest.skip("Chromium is not installed")
    site = DemoSite()
    browser = PlaywrightBrowser()
    await browser.start()
    try:
        session = await browser.open(site.url)
        agent = BrowserAgent(
            JevPolicy(CatalogJev(), model="typesafe-ai/jev", provider="vercel"),
            max_steps=6,
        )
        result = await agent.run(DEMO_GOAL, session)
    finally:
        await browser.stop()
        site.close()
    assert result.status == "done"
    assert "$18" in result.output_text
    assert "Alps Guide" in result.output_text
    assert [step.operation for step in result.steps] == ["TYPE_TEXT", "CLICK", "DONE"]
