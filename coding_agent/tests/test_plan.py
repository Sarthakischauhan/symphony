"""Tests for plan mode and workspace plan storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core_ai import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent import CodingAgent, PlanStore


def test_plan_store_saves_latest_plan(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    store.save("Add plan mode", "1. Inspect the TUI.\n2. Add tests.")

    assert store.path == tmp_path / "add_plan_mode_plan.md"
    assert "**Task:** Add plan mode" in store.load()
    assert "2. Add tests." in store.to_markdown()


def test_plan_store_writes_streamed_plan_to_task_named_file(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    path = store.begin("To build a server!")
    store.append("1. Inspect")
    store.append(" the API.\n")

    assert path == tmp_path / "to_build_a_server_plan.md"
    assert store.load().endswith("1. Inspect the API.\n")


def test_plan_mode_uses_read_only_tools_and_saves_result(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:test",
        workspace=tmp_path,
        enable_learning=False,
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

    assert captured["tools"] == ["read_file", "search"]
    assert "You are in plan mode." in str(captured["prompt"])
    assert list(agent.harness.tools) == [
        "read_file",
        "write_file",
        "patch",
        "bash",
        "search",
    ]
    assert "Make the change" in agent.plan_store.load()
