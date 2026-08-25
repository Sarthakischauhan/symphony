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
from coding_agent.agent import DEFAULT_MAX_TURNS, DEFAULT_MAX_TOKENS, DEFAULT_MAX_TOOL_CALLS


def test_coding_agent_defaults_are_safer_and_learning_is_enabled(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[],
    )
    assert agent.learning_loop is not None
    assert agent.harness.max_turns == DEFAULT_MAX_TURNS == 24
    assert agent.harness.limits.max_tool_calls == DEFAULT_MAX_TOOL_CALLS
    assert agent.harness.limits.max_tokens == DEFAULT_MAX_TOKENS
    assert agent.harness.limits.max_runtime_seconds == 600.0


def test_coding_agent_registers_spawn_agent_on_default_tools(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        enable_learning=False,
        auto_approve=True,
    )
    assert "spawn_agent" in agent.harness.tools
    assert "read_file" in agent.harness.tools

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
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        control_plane=control_plane,
        enable_learning=False,
        tools=[],
        context_limits={"fake:test-model": 100},
        context_warn_threshold=30,
        context_compact_threshold=20,
        compaction_keep_recent=2,
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

        assert [message.content for message in registry.calls[0][1:]] == [
            history[-1].content,
            "new request",
        ]
        assert len(result.messages) == 4
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
