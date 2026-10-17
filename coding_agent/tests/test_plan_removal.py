"""Retired planning tools must not be advertised or bypass ordinary approvals."""

import asyncio
import json
from pathlib import Path

import pytest

from coding_agent import CodingAgent
from coding_agent.addons.approvals import ApprovalAddon
from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig
from scripted_registry import ScriptedRegistry


def test_agent_has_one_workflow_and_keeps_approval_gate(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ScriptedRegistry({}),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False),
            langfuse=LangfuseConfig(enabled=False),
        ),
    )
    assert not {"enter_plan_mode", "exit_plan_mode"} & agent.harness.tools.keys()
    assert agent.harness.find_addon(ApprovalAddon) is agent.approval
    assert "write_file" in agent.harness.tools
    assert not hasattr(agent, "mode")
    assert not hasattr(agent, "plan_mode")
    assert not hasattr(agent, "plan_store")
    assert not (tmp_path / ".symphony" / "plans").exists()
    assert "todo" not in agent._checkpoint_metadata()


def test_removed_python_mode_argument_is_not_silently_ignored(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="mode"):
        CodingAgent(
            registry=ScriptedRegistry({}),  # type: ignore[arg-type]
            model_id="fake:test-model",
            workspace=tmp_path,
            mode="plan",
        )


@pytest.mark.parametrize("mode", ["plan", "unknown"])
def test_direct_run_rejects_legacy_mode_before_provider_call(tmp_path: Path, mode: str) -> None:
    registry = ScriptedRegistry({})
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False),
            langfuse=LangfuseConfig(enabled=False),
        ),
    )
    directory = agent.persistence.session_dir(agent.session_id)
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / "state.json"
    original = json.dumps({"mode": mode, "effort": "high"})
    state.write_text(original)
    with pytest.raises(ValueError, match="fresh session"):
        asyncio.run(agent.run("continue"))
    assert registry.calls == []
    assert state.read_text() == original
    assert agent._active_runs == 0
