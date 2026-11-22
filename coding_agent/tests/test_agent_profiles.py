from pathlib import Path

import pytest

from coding_agent.agent import CodingAgent
from coding_agent.config.agent_profiles import AgentProfile, load_agent_profile
from core_ai.registry import ModelRegistry


def test_profile_precedence_and_validation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = tmp_path / "project"
    monkeypatch.setenv("SYMPHONY_HOME", str(home))
    (home / "agents").mkdir(parents=True)
    (home / "agents" / "reviewer.yml").write_text("model: user:model\n")
    project = workspace / ".symphony" / "agents"
    project.mkdir(parents=True)
    (project / "reviewer.yaml").write_text(
        "name: reviewer\nmodel: project:model\ninstructions: Review carefully.\ntools: [read_file, search]\n"
    )
    profile = load_agent_profile(workspace, "reviewer")
    assert profile == AgentProfile("reviewer", "project:model", "Review carefully.", ("read_file", "search"))
    with pytest.raises(ValueError, match="invalid agent profile name"):
        load_agent_profile(workspace, "../reviewer")
    (project / "reviewer.yaml").write_text("tools: bash\n")
    with pytest.raises(ValueError, match="tools must be"):
        load_agent_profile(workspace, "reviewer")
    (project / "reviewer.yaml").write_text("permission: full-access\n")
    with pytest.raises(ValueError, match="invalid agent profile fields"):
        load_agent_profile(workspace, "reviewer")


def test_profile_filters_tools_and_adds_instructions(tmp_path: Path):
    agent = CodingAgent(
        registry=ModelRegistry(), model_id="test:model", workspace=tmp_path,
        profile=AgentProfile("reviewer", instructions="Review carefully.", tools=("read_file", "search")),
    )
    assert set(agent.harness.tools) == {"read_file", "search"}
    assert "Review carefully." in agent.harness.system_prompt
    agent.reload_user_addons()
    assert set(agent.harness.tools) == {"read_file", "search"}
    agent.dispose_user_addons()


def test_unknown_profile_tool_fails(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown profile tools: missing"):
        CodingAgent(registry=ModelRegistry(), model_id="test:model", workspace=tmp_path,
                    profile=AgentProfile("bad", tools=("missing",)))
