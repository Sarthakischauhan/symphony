"""The agent dashboard lists live processes in the subagent-list layout."""

from __future__ import annotations

import asyncio

from textual.app import App

from coding_agent.addons.persistence.active import ActiveSession
from coding_agent.resources.usage import AgentUsage
from coding_agent.tui.screens.dashboard import AgentDashboard


class Host(App[None]):
    def on_mount(self) -> None:
        self.push_screen(AgentDashboard())


def test_dashboard_lists_agents_and_closes(monkeypatch) -> None:
    monkeypatch.setattr(
        "coding_agent.tui.screens.dashboard.list_active",
        lambda: [
            ActiveSession(
                session_id="abcdef123456",
                pid=4321,
                kind="tui",
                workspace="/work/symphony",
                model_id="openai:test",
            )
        ],
    )
    monkeypatch.setattr(
        "coding_agent.tui.screens.dashboard.sample_usage",
        lambda pid, **_kwargs: (
            AgentUsage(pid=pid, alive=True, cpu_percent=4, rss_bytes=1024, disk_bytes=2048),
            1.0,
            2.0,
        ),
    )

    async def _run() -> None:
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            rendered = app.screen.query_one("#agent-dashboard").get_option_at_index(0).prompt.plain
            assert "symphony" in rendered
            assert "openai:test" in rendered
            assert "cpu" in rendered and "ram" in rendered and "disk" in rendered
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, AgentDashboard)

    asyncio.run(_run())


def test_dashboard_empty_state(monkeypatch) -> None:
    monkeypatch.setattr("coding_agent.tui.screens.dashboard.list_active", lambda: [])

    async def _run() -> None:
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            rendered = str(app.screen.query_one("#agent-dashboard").get_option_at_index(0).prompt)
            assert "No agents are running." in rendered

    asyncio.run(_run())
