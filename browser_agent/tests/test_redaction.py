"""Secret field values never reach Jev, events, or traces."""

from __future__ import annotations

import asyncio

import pytest

from browser_agent.jev_questions import build_questions, build_state
from browser_agent.models import Element, Observation
from browser_agent.redact_secret_fields import is_secret_field, redact_typed
from browser_agent.demo_site import DemoSite
from browser_agent.session import MAX_ELEMENTS, MAX_OPTIONS, MAX_PAGE_TEXT, PlaywrightBrowser, _SNAPSHOT_JS

LOGIN_HTML = """<!doctype html><title>Login</title>
<input type="text" aria-label="Email" value="me@example.test">
<input type="password" placeholder="Enter code" value="s3cret">
<input type="text" autocomplete="one-time-code" aria-label="Code" value="424242">
<input type="password" value="hunter2">
<input type="password" aria-label="Confirm">
"""


def _field(name: str, **extra) -> Element:
    return Element(index=1, role="input", name=name, kind="type", **extra)


def test_page_marked_secret_wins_over_a_generic_name() -> None:
    field = _field("Enter code", value="s3cret", secret=True)
    assert is_secret_field(field)
    assert redact_typed(field, "s3cret") == "***"
    assert field.label().endswith("· ***")
    assert field.compact()["value"] == "***"
    page = Observation(url="https://example.test/login", elements=[field])
    assert "s3cret" not in str(build_state("Log in.", page, [])) + str(build_questions(page, "Log in.", []))


def test_name_pattern_catches_unmarked_secrets_only() -> None:
    assert all(is_secret_field(_field(name)) for name in ("Password", "OTP", "PIN", "CVV", "Card number"))
    assert not any(is_secret_field(_field(name)) for name in ("Hotpot recipes", "Shipping address", "Search"))
    assert redact_typed(_field("Search"), "travel") == "travel"
    assert redact_typed(None, "travel") == "travel"


async def _snapshot() -> dict:
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
        await session.page.set_content(LOGIN_HTML)
        observation = await session.observe()
        raw = await session.page.evaluate(_SNAPSHOT_JS, [MAX_ELEMENTS, MAX_OPTIONS, MAX_PAGE_TEXT])
    finally:
        await browser.stop()
        site.close()
    return {"observation": observation, "raw": raw}


def test_snapshot_never_contains_a_secret_value() -> None:
    snapshot = asyncio.run(_snapshot())
    raw = str(snapshot["raw"])
    for secret in ("s3cret", "424242", "hunter2"):
        assert secret not in raw
    elements = snapshot["observation"].elements
    assert [element.secret for element in elements] == [False, True, True, True, True]
    assert [element.value for element in elements] == ["me@example.test", "***", "***", "***", ""]
