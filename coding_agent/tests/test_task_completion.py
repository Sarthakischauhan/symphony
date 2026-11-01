"""A scripted coding task is not done until the change, test, and verification exist."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core_ai.types import Message, StreamEvent
from core_harness import EventSink

from coding_agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LearningConfig, PluginsConfig


class _StoppingRegistry:
    """Plays tool turns, then tries to stop. The test decides whether that is allowed."""

    def __init__(self, turns: list[list[tuple[str, dict]]], done: str) -> None:
        self.turns = turns
        self.done = done
        self.calls = 0

    async def stream(self, model_id, messages, tools=None, **kwargs):
        del model_id, messages, tools, kwargs
        step = self.calls
        self.calls += 1
        if step < len(self.turns):
            for index, (name, args) in enumerate(self.turns[step]):
                payload = dict(args)
                payload.setdefault("activity", {"verb": "Testing", "reason": "Script the task."})
                yield StreamEvent(
                    type="toolcall_start", content_index=index,
                    tool_call_id=f"c{step}-{index}", tool_name=name,
                )
                yield StreamEvent(type="toolcall_delta", content_index=index, delta=json.dumps(payload))
        else:
            yield StreamEvent(type="text_delta", delta=self.done)
        yield StreamEvent(type="done")


def _task(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    package = workspace / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "clamp.py").write_text(
        "def clamp(value, low, high):\n    return value\n",
        encoding="utf-8",
    )
    (workspace / "test_clamp.py").write_text(
        "from sample.clamp import clamp\n\n\ndef test_inside_range():\n    assert clamp(2, 0, 5) == 2\n",
        encoding="utf-8",
    )
    return workspace


def _agent(workspace: Path, registry: _StoppingRegistry) -> CodingAgent:
    return CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=workspace,
        sink=EventSink(),
        tools=None,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False),
            plugins=PluginsConfig(enabled=True),
        ),
    )


def _tool_names(agent: CodingAgent) -> list[str]:
    names: list[str] = []
    for event in agent.sink.events:
        if event.event_type != "tool_execution_started":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        name = payload.get("tool_name")
        if isinstance(name, str):
            names.append(name)
    return names


def test_shipped_plugin_is_visible_and_old_skills_still_load(tmp_path: Path) -> None:
    agent = _agent(tmp_path, _StoppingRegistry([], "idle"))
    ids = {skill.skill_id for skill in agent.skill_registry.skills}
    assert "bundled/systematic-debug" in ids
    assert "bundled/addon-authoring" in ids
    assert "plugin/reliability/finish-the-task" in ids
    assert "plugin/reliability/test-first" in ids
    assert "plugin/reliability/edge-cases" not in ids
    assert any(plugin.plugin_id == "reliability" and plugin.enabled for plugin in agent.loaded_plugins)
    prompt = agent.harness.system_prompt
    assert "plugin/reliability/finish-the-task" in prompt
    assert "SKILL.md" not in prompt.split("Skills", 1)[-1]


def test_partial_fix_does_not_count_as_a_finished_task(tmp_path: Path) -> None:
    workspace = _task(tmp_path)
    registry = _StoppingRegistry(
        [[
            ("patch", {
                "path": "sample/clamp.py",
                "old_str": "    return value\n",
                "new_str": "    return min(max(value, low), high)\n",
            }),
        ]],
        "done",
    )
    agent = _agent(workspace, registry)
    result = asyncio.run(agent.run("Clamp values to the inclusive range, with tests."))
    assert _tool_names(agent).count("bash") == 0
    assert "def test_low_bound" not in (workspace / "test_clamp.py").read_text(encoding="utf-8")
    assert "done" in result.output_text
    # The unfinished repo is the signal: the model stopped before verification.
    assert registry.calls == 2


def test_complete_task_changes_tests_and_verifies(tmp_path: Path) -> None:
    workspace = _task(tmp_path)
    implementation = "    return min(max(value, low), high)\n"
    tests = (
        "from sample.clamp import clamp\n\n\n"
        "def test_inside_range():\n    assert clamp(2, 0, 5) == 2\n\n"
        "def test_low_bound():\n    assert clamp(-1, 0, 5) == 0\n\n"
        "def test_high_bound():\n    assert clamp(9, 0, 5) == 5\n"
    )
    registry = _StoppingRegistry(
        [
            [("skill", {"skill_id": "plugin/reliability/test-first"})],
            [("write_file", {"path": "test_clamp.py", "content": tests})],
            [("bash", {"command": "python -m pytest test_clamp.py -q"})],
            [("patch", {"path": "sample/clamp.py", "old_str": "    return value\n", "new_str": implementation})],
            [("skill", {"skill_id": "plugin/reliability/finish-the-task"})],
            [("bash", {"command": "python -m pytest test_clamp.py -q"})],
        ],
        "Clamped the inclusive range. pytest: passed.",
    )
    agent = _agent(workspace, registry)
    result = asyncio.run(agent.run("Clamp values to the inclusive range, with tests."))
    assert (workspace / "sample" / "clamp.py").read_text(encoding="utf-8").count(implementation) == 1
    text = (workspace / "test_clamp.py").read_text(encoding="utf-8")
    assert "def test_low_bound" in text and "def test_high_bound" in text
    names = _tool_names(agent)
    assert names.count("bash") >= 2
    assert "skill" in names and "write_file" in names and "patch" in names
    assert "pytest: passed" in result.output_text
    assert isinstance(result.messages[-1], Message)
