import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

from textual.widgets import Static

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.screens.usage import UsageScreen
from core_ai.quota import QuotaResult, QuotaWindow


def test_usage_meters_use_context_glyphs_and_window_colors():
    rendered = UsageScreen._format([QuotaResult("openai", (
        QuotaWindow("Codex · 5 hour", 50),
        QuotaWindow("Codex · 7 day", 100),
        QuotaWindow("Other", 0),
    ))])
    assert "█" * 11 + "░" * 11 in rendered.plain
    assert "█" * 22 in rendered.plain
    assert "░" * 22 in rendered.plain
    assert any(span.style == "#b49ad8" for span in rendered.spans)
    assert any(span.style == "#c7b66e" for span in rendered.spans)


def test_usage_labels_are_consistent_and_keep_additional_pools():
    results = [
        QuotaResult("openai", (QuotaWindow("Codex · 5 hour", 25), QuotaWindow("Codex · 7 day", 50), QuotaWindow("Spark · 7 day", 10))),
        QuotaResult("anthropic", (QuotaWindow("Five Hour", 20), QuotaWindow("Seven Day", 30), QuotaWindow("Seven Day Sonnet", 40))),
    ]
    text = UsageScreen._format(results).plain
    assert "Codex" not in text
    assert text.count("\n5 hours\n") == 2
    assert text.count("\n7 days\n") == 2
    assert "Spark · 7 days" in text
    assert "7 days · Sonnet" in text


def test_usage_layout_and_relative_resets():
    now = datetime.now(timezone.utc)
    result = QuotaResult("openai", (
        QuotaWindow("5 hour", 25, now + timedelta(hours=2, minutes=5)),
        QuotaWindow("7 day", 60, now + timedelta(days=2, hours=3)),
        QuotaWindow("Expired", 0, now - timedelta(seconds=1)),
    ))
    text = UsageScreen._format([result]).plain
    assert "OpenAI\n\n5 hours\n█" in text
    assert "7 days\n█" in text
    assert "resets in 2 hours" in text
    assert "resets in 2 days" in text
    assert "reset time passed" in text


def test_usage_opens_without_blocking_and_refreshes(monkeypatch, tmp_path: Path):
    calls = []
    gate = None

    async def fetch(provider, *, refresh=False):
        calls.append((provider, refresh))
        await gate.wait()
        return QuotaResult(provider, (QuotaWindow("Weekly", 42),))

    monkeypatch.setattr("coding_agent.tui.screens.usage.configured_provider_ids", lambda: ("openai",))
    monkeypatch.setattr("coding_agent.tui.screens.usage.quota_service.get", fetch)
    app = CodingAgentApp(workspace=tmp_path)

    async def run():
        nonlocal gate
        gate = asyncio.Event()
        async with app.run_test() as pilot:
            await app._command_manager.run("/usage")
            await pilot.pause()
            assert isinstance(app.screen, UsageScreen)
            assert "Loading" in str(app.screen.query_one("#usage-results", Static).render())
            gate.set()
            await pilot.pause()
            assert "42% used" in str(app.screen.query_one("#usage-results", Static).render())
            await pilot.press("r")
            await pilot.pause()
            assert calls == [("openai", False), ("openai", True)]
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, UsageScreen)

    asyncio.run(run())
