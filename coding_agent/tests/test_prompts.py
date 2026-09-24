"""Product system prompts stay distinct for parent vs child."""

from __future__ import annotations

from pathlib import Path

from coding_agent.agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LearningConfig, default_coding_agent_harness
from coding_agent.personalities import PERSONALITY_HEADING, compose_system_prompt, get
from coding_agent.prompts import SUBAGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from core_ai import ModelRegistry
from core_harness import EventSink
from core_harness.addons.subagent import ChildConfig, ChildIdentity, SubagentAddon


def test_system_prompt_compose_ends_with_personality() -> None:
    addon = get("direct").system_addon  # type: ignore[union-attr]
    prompt = compose_system_prompt(SYSTEM_PROMPT, "direct")
    assert PERSONALITY_HEADING in prompt
    assert prompt.rstrip().endswith(addon)
    assert prompt.index("You are a coding agent") < prompt.index(PERSONALITY_HEADING)


def test_product_harness_uses_subagent_system_prompt() -> None:
    harness = default_coding_agent_harness()
    assert harness.subagent_system_prompt == SUBAGENT_SYSTEM_PROMPT
    assert "No preamble" in harness.subagent_system_prompt
    assert "compact final" in harness.subagent_system_prompt
    assert "want me to" in harness.subagent_system_prompt
    assert "You are a coding agent" not in harness.subagent_system_prompt
    assert "autonomous software engineering agent" not in harness.subagent_system_prompt


def test_child_system_prompt_is_subagent_not_main(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:test",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    assert agent.harness.config.subagent_system_prompt == SUBAGENT_SYSTEM_PROMPT
    addon = next(a for a in agent.harness.addons if a.name == "subagent")
    assert isinstance(addon, SubagentAddon)
    child = addon.build_child(
        agent.harness,
        ChildIdentity(
            agent_id="child-1",
            parent_id=agent.harness.agent_id or "parent",
            spawn_depth=1,
            label="probe",
            prompt_text="do the thing",
            sink=EventSink(),
            parent_session_id=agent.harness.session_id or "parent-session",
        ),
        child_config=ChildConfig(),
    )
    prompt = child.system_prompt
    assert "delegated task" in prompt
    assert "No preamble" in prompt
    assert "compact final" in prompt
    assert "You are a coding agent" not in prompt
    assert "autonomous software engineering agent" not in prompt
    assert PERSONALITY_HEADING not in prompt
