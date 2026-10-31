"""The agent dashboard lists live processes in the subagent-list layout."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

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


def test_dashboard_lists_only_live_background_tasks(monkeypatch) -> None:
    monkeypatch.setattr("coding_agent.tui.screens.dashboard.list_active", lambda: [])

    async def _run() -> None:
        running = asyncio.create_task(asyncio.sleep(30))
        finished = asyncio.create_task(asyncio.sleep(0))
        await finished
        harness = SimpleNamespace(child_tasks={
            "job": SimpleNamespace(status="background", task=running, label="bash:pytest -q", child_id="job12345"),
            "agent": SimpleNamespace(status="running", task=running, label="review", child_id="agent123"),
            "done": SimpleNamespace(status="background", task=finished, label="bash:done", child_id="done1234"),
        })
        app = Host()
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.screen.harness = harness
                app.screen.refresh_agents()
                options = app.screen.query_one("#agent-dashboard")
                assert options.option_count == 2
                assert "pytest -q" in options.get_option_at_index(0).prompt.plain
                assert "subagent" in options.get_option_at_index(1).prompt.plain
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                app.screen.refresh_agents()
                assert "No agents are running" in str(options.get_option_at_index(0).prompt)
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)

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
