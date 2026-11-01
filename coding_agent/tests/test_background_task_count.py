"""The top bar counts live background jobs through a typed source, not by probing the app."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.chrome import TopBar, running_background_tasks
from core_harness.addons.subagent.background import ChildTask
from test_new_session_chrome import bars


def _record(child_id: str, status: str, task: asyncio.Task[None] | None) -> ChildTask:
    return ChildTask(child_id, "agent", "session", child_id, status=status, task=task)


def test_only_live_running_or_background_records_count() -> None:
    async def _run() -> int:
        live = asyncio.create_task(asyncio.sleep(60))
        finished = asyncio.create_task(asyncio.sleep(0))
        await finished
        try:
            return running_background_tasks({
                "a": _record("a", "running", live),
                "b": _record("b", "background", live),
                "c": _record("c", "running", None),
                "d": _record("d", "running", finished),
                "e": _record("e", "completed", live),
                "f": _record("f", "failed", None),
            })
        finally:
            live.cancel()
            await asyncio.gather(live, return_exceptions=True)

    assert asyncio.run(_run()) == 3
    assert running_background_tasks({}) == 0


def test_the_top_bar_polls_the_source_it_was_given(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> list[str]:
        seen = []
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause()
            assert app.background_task_count() == 0
            task = asyncio.create_task(asyncio.sleep(60))
            app._agent = SimpleNamespace(harness=SimpleNamespace(child_tasks={"j": _record("j", "running", task)}))
            app.query_one("#topbar", TopBar)._refresh_background_tasks()
            seen.append(bars(app)[0])
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            app.query_one("#topbar", TopBar)._refresh_background_tasks()
            seen.append(bars(app)[0])
            app._agent = None
        return seen

    with_job, without = asyncio.run(_run())
    assert "1 Background task" in with_job and "Background" not in without
