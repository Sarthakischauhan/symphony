"""``/new`` leaves the top bar and footer empty, not showing the old session."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.chrome import SessionChrome
from core_harness.addons.subagent.background import ChildTask

CONTEXT_LIMIT = 100_000


def _plain(renderable: Any, *, width: int = 120) -> str:
    console = Console(width=width, file=io.StringIO(), force_terminal=False, color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def bars(app: CodingAgentApp) -> tuple[str, str]:
    """The top bar and footer exactly as drawn."""
    return _plain(app.query_one("#topbar").content), _plain(app.query_one("#status").content)


class FakeHarness:
    """The slice of the harness ``/new`` and the bars use. Cancels tasks like the real one."""

    model_id = "openai:gpt-4o-mini"

    def __init__(self) -> None:
        self.session_id = "old-session"
        self.child_tasks: dict[str, ChildTask] = {}
        self.state = SimpleNamespace(context_limit=lambda _model: CONTEXT_LIMIT)

    async def shutdown_children(self) -> None:
        tasks = [record.task for record in self.child_tasks.values() if record.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def drain_child_results(self) -> list[Any]:
        return []


async def fill_session(app: CodingAgentApp, harness: FakeHarness, artifact_dir: Path) -> asyncio.Task[None]:
    """A turn with usage, cost and an artifact, plus one running background task."""
    presenter = app._presenter
    assert presenter is not None
    presenter.handle("run_started", {"session_id": "old-session"})
    presenter.handle(
        "usage",
        {
            "prompt_tokens": 40_000,
            "completion_tokens": 2_000,
            "total_tokens": 42_000,
            "cumulative_tokens": 42_000,
            "model_id": harness.model_id,
            "model_costs": {harness.model_id: 0.37},
        },
    )
    presenter.handle(
        "context",
        {"context_limit": CONTEXT_LIMIT, "context_left": 58_000, "tokens_used": 42_000, "utilization": 0.42},
    )
    presenter.handle(
        "artifact_created",
        {"path": str(artifact_dir / "artifacts" / "a1" / "v1" / "report.html"), "title": "Report", "kind": "html", "version": 1},
    )
    task = asyncio.create_task(asyncio.sleep(60))
    harness.child_tasks["job"] = ChildTask("job", "agent", "old-session", "bash:sleep", task=task)
    app._refresh_background_tasks()
    return task


def test_new_session_resets_top_bar_and_footer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    harness = FakeHarness()
    agent = SimpleNamespace(session_id="old-session", harness=harness, learning_loop=None)

    def bind_session(session_id: str) -> None:
        agent.session_id = session_id
        harness.session_id = session_id

    agent.bind_session = bind_session

    async def _run() -> None:
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app._agent = agent 
            task = await fill_session(app, harness, tmp_path)
            await pilot.pause()

            topbar, footer = bars(app)
            assert "1 artifact" in topbar and "1 Background task" in topbar
            assert "42% context" in footer and "42,000/100,000" in footer and "$0.37" in footer

            await app._run_slash_command("/new")
            await pilot.pause()

            topbar, footer = bars(app)
            assert "artifact" not in topbar and "Background" not in topbar
            assert "0% context" in footer and "0/100,000" in footer and "$0.00" in footer
            assert "42" not in footer and "$0.37" not in footer
            assert task.cancelled()
            assert app._session_artifacts == {}
            assert app._ui_state.metrics.model_costs == {}

            app.reset_session_chrome(SessionChrome(context_limit=CONTEXT_LIMIT, tokens_used=30_000, costs={"m": 0.5}))
            topbar, footer = bars(app)
            assert "30% context" in footer and "$0.50" in footer

    asyncio.run(_run())
