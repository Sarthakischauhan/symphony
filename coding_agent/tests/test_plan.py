"""Tests for plan mode and workspace plan storage."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from core_ai import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent import CodingAgent, PlanStore
from coding_agent.config import CodingAgentConfig, LearningConfig
from coding_agent.plan_mode import PlanModeState
from coding_agent.tui.commands.manager import on_plan_action


def test_plan_store_saves_latest_plan(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    store.save("Add plan mode", "1. Inspect the TUI.\n2. Add tests.")

    assert store.path == tmp_path / ".symphony" / "plans" / "add_plan_mode_plan.md"
    assert "**Task:** Add plan mode" in store.load()
    assert "2. Add tests." in store.to_markdown()


def test_plan_store_writes_streamed_plan_to_task_named_file(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    path = store.begin("To build a server!")
    store.append("1. Inspect")
    store.append(" the API.\n")

    assert path == tmp_path / ".symphony" / "plans" / "to_build_a_server_plan.md"
    assert store.load().endswith("1. Inspect the API.\n")

    store.save("Add authentication", "1. Add sessions.")
    assert [item.name for item in store.list_paths()] == [
        "add_authentication_plan.md",
        "to_build_a_server_plan.md",
    ]
    assert store.select("to_build_a_server_plan.md") == path
    assert store.path == path


def test_plan_mode_uses_read_only_tools_and_saves_result(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:test",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    captured: dict[str, object] = {}

    async def fake_run(user_input: str, **kwargs: object) -> HarnessResult:
        captured["tools"] = list(agent.harness.tools)
        captured["prompt"] = agent.harness.system_prompt
        return HarnessResult(
            output_text="1. Read the code.\n2. Make the change.",
            messages=[
                Message(role="user", content=user_input),
                Message(role="assistant", content="1. Read the code.\n2. Make the change."),
            ],
        )

    agent.harness.run = fake_run  # type: ignore[method-assign]
    agent.set_mode("plan")
    asyncio.run(agent.run("Add a feature"))

    assert set(captured["tools"]) >= {"read_file", "search", "bash"}
    assert "You are in plan mode." in str(captured["prompt"])
    assert set(agent.harness.tools) >= {
        "read_file", "write_file", "generate_image", "patch", "bash",
        "search", "ask_user", "spawn_agent", "enter_plan_mode", "exit_plan_mode",
    }
    assert "Make the change" not in agent.plan_store.load()


class _PlanGateAgent:
    def __init__(self, workspace: Path) -> None:
        self.mode = "build"
        self.plan_mode = PlanModeState(workspace=workspace)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "plan":
            self.plan_mode.begin()
        else:
            self.plan_mode.reset()


def _plan_gate_app(tmp_path: Path, *, mode: str = "build") -> SimpleNamespace:
    store = PlanStore(tmp_path)
    store.save("Ship feature", "1. Build it.")
    agent = _PlanGateAgent(tmp_path)
    if mode == "plan":
        agent.set_mode("plan")
        agent.plan_mode.begin(str(store.path))
    prompt = SimpleNamespace(focused=False)
    prompt.focus = lambda: setattr(prompt, "focused", True)
    app = SimpleNamespace(
        mode=mode,
        _busy=False,
        _agent=agent,
        _plan_store=store,
        hint_updated=False,
        prompt=prompt,
    )
    app._update_composer_hint = lambda: setattr(app, "hint_updated", True)
    app.query_one = lambda _selector: prompt
    return app


def test_request_changes_from_build_activates_plan_gate(tmp_path: Path) -> None:
    app = _plan_gate_app(tmp_path, mode="build")
    other = tmp_path / "src.py"

    on_plan_action(app, "changes")

    assert app.mode == "plan"
    assert app._agent.mode == "plan"
    assert app._agent.plan_mode.active
    assert app._agent.plan_mode.plan_path == str(app._plan_store.path.resolve())
    assert not app._agent.plan_mode.permits("write_file", target=str(other))
    assert app._agent.plan_mode.permits("write_file", target=str(app._plan_store.path))
    assert app.prompt.focused


def test_plan_quit_resets_plan_gate(tmp_path: Path) -> None:
    app = _plan_gate_app(tmp_path, mode="plan")
    assert app._agent.plan_mode.active

    on_plan_action(app, "quit")

    assert app.mode == "build"
    assert app._agent.mode == "build"
    assert not app._agent.plan_mode.active
    assert app._agent.plan_mode.permits("write_file", target=str(tmp_path / "src.py"))
