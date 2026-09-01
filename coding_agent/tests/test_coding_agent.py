import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from core_ai import ModelRegistry
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
from core_harness import NullControlPlane
from coding_agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LearningConfig, spawn_settings_path


def test_coding_agent_defaults_are_safer_and_learning_is_enabled(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[],
    )
    assert agent.learning_loop is not None
    defaults = CodingAgentConfig().harness
    assert agent.harness.max_turns == defaults.max_turns == 24
    assert agent.harness.limits.max_tool_calls == defaults.max_tool_calls
    assert agent.harness.limits.max_tokens == defaults.max_tokens
    assert agent.harness.limits.max_runtime_seconds == 600.0
    settings_path = spawn_settings_path(tmp_path)
    assert settings_path.exists()
    saved = CodingAgentConfig.model_validate_json(settings_path.read_text(encoding="utf-8"))
    assert saved.harness.max_turns == 24
    assert saved.harness.tool_result_prune_tokens == 48_000
    assert saved.harness.context_compact_threshold == 16_000
    assert saved.harness.compaction_keep_recent == 10


def test_coding_agent_registers_spawn_agent_on_default_tools(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    assert "spawn_agent" in agent.harness.tools
    assert "read_file" in agent.harness.tools


def test_coding_agent_child_runs_without_approvals(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualControlPlane

    plane = TextualControlPlane(workspace=tmp_path)
    plane.set_approval_mode("ask")
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        control_plane=plane,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    cfg = agent._spawn_child_config(
        prompt="x",
        max_turns=99,
        model_id=" fake:child ",
    )
    assert cfg.model_id == "fake:child"
    assert cfg.max_turns == agent.harness.config.spawn_max_turns
    assert cfg.control_plane is not None
    assert cfg.control_plane is not plane
    assert cfg.control_plane.approvals.mode == "always_allow"
    assert plane.approvals.mode == "ask"
    assert cfg.control_plane.cancel_event is plane.cancel_event
    allowed = asyncio.run(
        cfg.control_plane.approve_tool_call(
            tool_name="bash",
            arguments={"command": "ls"},
        )
    )
    assert allowed is True


def test_coding_agent_child_stays_autonomous_if_parent_already_allows(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualControlPlane

    plane = TextualControlPlane(workspace=tmp_path)
    plane.set_approval_mode("always_allow")
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        control_plane=plane,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    cfg = agent._spawn_child_config()
    assert cfg.control_plane is not None
    assert cfg.control_plane.approvals.mode == "always_allow"
    assert plane.approvals.mode == "always_allow"

load_dotenv(override=True)


class CapturingRegistry:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict]):
        self.calls.append(list(messages))
        yield StreamEvent(type="text_delta", delta="done")
        yield StreamEvent(
            type="usage",
            prompt_tokens=10,
            completion_tokens=1,
            total_tokens=11,
        )
        yield StreamEvent(type="done")


def test_coding_agent_compacts_oversized_persisted_context(tmp_path: Path) -> None:
    registry = CapturingRegistry()
    control_plane = NullControlPlane()
    config = CodingAgentConfig()
    config = config.model_copy(
        update={
            "learning": config.learning.model_copy(update={"enabled": False}),
            "harness": config.harness.model_copy(
                update={
                    "context_limits": {"fake:test-model": 100},
                    "context_warn_threshold": 30,
                    "context_compact_threshold": 20,
                    "compaction_keep_recent": 2,
                }
            ),
        }
    )
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        control_plane=control_plane,
        config=config,
        tools=[],
    )

    async def _run() -> None:
        history = [
            Message(role="user", content=f"old message {index} " * 20)
            for index in range(6)
        ]
        await agent.persistence.save_conversation(
            session_id=agent.session_id,
            messages=history,
        )

        result = await agent.run("new request")

        sent = registry.calls[0]
        assert sent[0].role == "system"
        assert sent[1].content == history[0].content
        assert str(sent[2].content).startswith("[compacted earlier context]")
        assert sent[-2].content == history[-1].content
        assert sent[-1].content == "new request"
        assert len(result.messages) == len(sent) + 1
        saved = await agent.persistence.load_conversation(session_id=agent.session_id)
        assert saved == result.messages

    asyncio.run(_run())

    event_types = [event.event_type for event in control_plane.events]
    assert event_types.index("compaction_started") < event_types.index("turn_started")
    assert "compaction_completed" in event_types


def _build_live_agent(tmp_path: Path) -> CodingAgent:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("Set OPENAI_API_KEY to run the coding-agent integration test.")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("OPENAI_TEST_MODEL", "gpt-4o-mini")

    registry = ModelRegistry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))

    return CodingAgent(
        registry=registry,
        model_id=f"openai:{model_name}",
        workspace=tmp_path,
    )


def test_coding_agent_writes_and_runs_bubble_sort(tmp_path: Path) -> None:
    agent = _build_live_agent(tmp_path)

    result = asyncio.run(
        agent.run(
            "Create a file named sort_test.py in the workspace. "
            "Implement bubble sort for the array [14, 2, 19, 13, 3, 24]. "
            "Make the script runnable from the command line, run it with bash, "
            "and ensure it prints the sorted result [2, 3, 13, 14, 19, 24]. "
            "Use the write_file, read_file, bash, and grep tools as needed."
        )
    )
    print(result)
    sort_test = tmp_path / "sort_test.py"
    assert sort_test.exists()
    source = sort_test.read_text(encoding="utf-8")
    assert "bubble_sort" in source
    assert "def" in source

    run_result = subprocess.run(
        [sys.executable, "sort_test.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert run_result.stdout.strip() == "[2, 3, 13, 14, 19, 24]"
    assert result.output_text
    assert "[2, 3, 13, 14, 19, 24]" in result.output_text
