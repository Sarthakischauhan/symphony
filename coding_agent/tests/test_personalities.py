"""Personality catalog load, compose, persist, and picker matching."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from coding_agent.agent import CodingAgent
from coding_agent.config import (
    CodingAgentConfig,
    LearningConfig,
    ensure_spawn_settings,
    load_coding_agent_config,
)
from coding_agent.personalities import (
    PERSONALITY_BEGIN,
    compose_system_prompt,
    get,
    load_personalities,
)
from coding_agent.tui.commands.catalog import (
    find_personality,
    personality_matches,
    personality_options,
)
from coding_agent.tui.commands.manager import select_personality
from core_ai import ModelRegistry


def test_load_personalities_from_repo_catalog() -> None:
    rows = load_personalities()
    assert [row.id for row in rows] == [
        "direct",
        "bad_boy",
        "caveman",
        "precise",
        "warm",
    ]
    assert all(row.system_addon for row in rows)
    assert get("direct") is not None
    assert get("direct").name == "Direct"  # type: ignore[union-attr]


def test_load_personalities_missing_or_invalid_is_empty(tmp_path: Path) -> None:
    assert load_personalities(tmp_path / "missing.json") == ()
    broken = tmp_path / "personalities.json"
    broken.write_text("{", encoding="utf-8")
    assert load_personalities(broken) == ()
    broken.write_text(json.dumps({"personalities": "nope"}), encoding="utf-8")
    assert load_personalities(broken) == ()


def test_compose_inserts_personality_segment() -> None:
    addon = get("direct").system_addon  # type: ignore[union-attr]
    prompt = compose_system_prompt("BASE", "direct")
    assert prompt.startswith("BASE")
    assert addon in prompt
    assert PERSONALITY_BEGIN in prompt
    assert prompt.endswith("\n")


def test_compose_replaces_personality_segment_only() -> None:
    first = compose_system_prompt("BASE", "direct", plan="PLAN MODE")
    second = compose_system_prompt(first, "warm")
    assert get("direct").system_addon not in second  # type: ignore[union-attr]
    assert get("warm").system_addon in second  # type: ignore[union-attr]
    assert second.count(PERSONALITY_BEGIN) == 1
    assert "PLAN MODE" in second
    assert "BASE" in second


def test_compose_unknown_or_null_id_is_stock() -> None:
    assert compose_system_prompt("BASE", None).strip() == "BASE"
    assert compose_system_prompt("BASE", "not-a-personality").strip() == "BASE"
    assert PERSONALITY_BEGIN not in compose_system_prompt("BASE", "")


def test_config_personality_defaults_and_round_trip(tmp_path: Path) -> None:
    assert CodingAgentConfig().personality == "direct"
    written = ensure_spawn_settings(tmp_path, overrides={"personality": "warm"})
    assert written.personality == "warm"
    loaded = load_coding_agent_config(tmp_path)
    assert loaded.personality == "warm"
    cleared = ensure_spawn_settings(tmp_path, overrides={"personality": None})
    assert cleared.personality is None
    assert load_coding_agent_config(tmp_path).personality is None


def test_apply_system_prompt_updates_harness_immediately(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:test",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    assert get("direct").system_addon in agent.harness.system_prompt  # type: ignore[union-attr]
    agent.config.personality = "caveman"
    agent.apply_system_prompt()
    assert get("caveman").system_addon in agent.harness.system_prompt  # type: ignore[union-attr]
    assert get("direct").system_addon not in agent.harness.system_prompt  # type: ignore[union-attr]
    agent.set_mode("plan")
    assert "You are in plan mode." in agent.harness.system_prompt
    assert get("caveman").system_addon in agent.harness.system_prompt  # type: ignore[union-attr]


def test_personality_picker_matching() -> None:
    options = personality_options()
    assert [item.id for item in options] == [
        "direct",
        "bad_boy",
        "caveman",
        "precise",
        "warm",
    ]
    assert find_personality("direct").id == "direct"  # type: ignore[union-attr]
    assert find_personality("Bad boy").id == "bad_boy"  # type: ignore[union-attr]
    assert find_personality("missing") is None
    assert [item.id for item in personality_matches("cav")] == ["caveman"]


def test_select_personality_persists_and_recomposes(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:test",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    updates: list[str] = []
    notices: list[tuple] = []
    app = SimpleNamespace(
        workspace=tmp_path,
        config=agent.config,
        _agent=agent,
        add_update=updates.append,
        add_notice=lambda *args, **kwargs: notices.append(args),
    )

    select_personality(app, "precise")

    assert app.config.personality == "precise"
    assert agent.config.personality == "precise"
    assert get("precise").system_addon in agent.harness.system_prompt  # type: ignore[union-attr]
    assert load_coding_agent_config(tmp_path).personality == "precise"
    assert updates and "Precise" in updates[0]
    assert not notices

    select_personality(app, "nope")
    assert agent.config.personality == "precise"
    assert notices
