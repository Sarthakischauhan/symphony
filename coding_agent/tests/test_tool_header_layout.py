"""Card headers show their whole target and wrap instead of running off screen.

A card is first painted while its arguments are still streaming. For a patch the
path usually arrives after ``old_str`` and ``new_str``, so the first paint is just
"Update". The header must still show the path and diff stats once they arrive,
and never the raw JSON in between.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.tools.calls import BashToolWidget, PatchDiffWidget


def _lines(label) -> list[str]:
    return [label.render_line(y).text.rstrip() for y in range(label.size.height)]


def _app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CodingAgentApp:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return CodingAgentApp(workspace=tmp_path)


def test_patch_header_shows_the_path_that_streamed_in_after_the_first_paint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)
    paths = ["coding_agent/src/coding_agent/tools/ask_user.py", "coding_agent/tests/test_tui.py"]

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            presenter = app._presenter
            assert presenter is not None
            presenter.handle("run_started", {"run_id": "r1"})  # cards mount inside the run's process view
            for index, path in enumerate(paths):
                call_id = f"p{index}"
                # Real calls stream the activity label and the edit before the path.
                activity = {"verb": "Editing", "reason": "Support structured questions", "group": "implementation"}
                raw = json.dumps({"activity": activity, "old_str": "a = 1\n" * 40, "new_str": "a = 2\n" * 40, "path": path})
                presenter.handle("tool_call_started", {"tool_call_id": call_id, "tool_name": "patch"})
                chunks = [raw[:8]] + [raw[start:start + 60] for start in range(8, len(raw), 60)]
                for chunk in chunks:
                    presenter.handle("tool_call_delta", {"tool_call_id": call_id, "delta": chunk})
                    await pilot.pause(0.06)  # the card paints mid-stream, first with almost nothing
                    for card in app.query(PatchDiffWidget):
                        assert "{" not in " ".join(_lines(card._tool_label))  # never the raw JSON
                presenter.handle(
                    "tool_execution_started",
                    {"tool_call_id": call_id, "tool_name": "patch", "arguments": json.loads(raw)},
                )
                presenter.handle(
                    "tool_execution_completed",
                    {"tool_call_id": call_id, "tool_name": "patch", "status": "ok", "result": f"patched {path} at line 1"},
                )
            await pilot.pause(0.2)
            headers = [_lines(card._tool_label) for card in app.query(PatchDiffWidget)]
            assert headers == [["Update ask_user.py +40 -40"], ["Update test_tui.py +40 -40"]]

    asyncio.run(run())


def test_long_bash_header_wraps_inside_the_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)
    command = "uv run ruff check " + " ".join(f"coding_agent/src/coding_agent/module_{index}.py" for index in range(4))

    async def run() -> None:
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            presenter = app._presenter
            assert presenter is not None
            presenter.handle("tool_call_started", {"tool_call_id": "b1", "tool_name": "bash"})
            presenter.handle("tool_call_delta", {"tool_call_id": "b1", "delta": '{"command": "uv run'})
            await pilot.pause(0.1)
            presenter.handle(
                "tool_execution_started", {"tool_call_id": "b1", "tool_name": "bash", "arguments": {"command": command}}
            )
            presenter.handle(
                "tool_execution_completed", {"tool_call_id": "b1", "tool_name": "bash", "status": "ok", "result": "ok"}
            )
            await pilot.pause(0.2)
            label = app.query_one(BashToolWidget)._bash_label
            lines = _lines(label)
            assert len(lines) > 1
            assert all(len(line) <= label.size.width for line in lines)
            # Headers are capped at 180 characters; everything up to the cap is shown.
            assert " ".join(lines).startswith("Bash " + command[:120])

    asyncio.run(run())
