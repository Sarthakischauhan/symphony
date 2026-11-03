"""The catalog lists name, description and SKILL.md path; it is budgeted and deterministic."""

from __future__ import annotations

from pathlib import Path

from coding_agent.addons.skills import Skill, build_catalog, discover_skills
from coding_agent.addons.skills.catalog import CATALOG_HEADER
from coding_agent.addons.skills.models import CATALOG_DESCRIPTION_CHARS
from coding_agent.agent import CodingAgent
from coding_agent.config import SkillsConfig


def _skill(root: Path, name: str, description: str = "Do it.", extra: str = "") -> Skill:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\nBODY-SENTINEL\n", encoding="utf-8")
    return Skill(name, description, path, "user")


class _Registry:
    async def stream(self, *args, **kwargs):  # pragma: no cover - never called
        if False:
            yield None


def test_system_prompt_lists_path_not_body_and_registers_no_skill_tool(tmp_path: Path) -> None:
    skill = _skill(tmp_path / ".symphony" / "skills", "orient", "Map owners first.")
    agent = CodingAgent(registry=_Registry(), model_id="test:model", workspace=tmp_path)  # type: ignore[arg-type]
    prompt = agent.harness.system_prompt
    assert f"- orient: Map owners first. (file: {skill.path.resolve()})" in prompt
    assert "read its SKILL.md at the path shown" in prompt
    assert "BODY-SENTINEL" not in prompt
    assert "skill" not in agent.harness.tools


def test_catalog_line_is_name_description_and_path(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "orient", "x" * 500)
    catalog = build_catalog((skill,), settings={}, max_tokens=2000)
    (line,) = [entry.line for entry in catalog.entries]
    assert line == f"- orient: {'x' * (CATALOG_DESCRIPTION_CHARS - 1)}… (file: {skill.path})"
    assert catalog.text == f"{CATALOG_HEADER}\n{line}"


def test_catalog_is_sorted_and_identical_for_any_discovery_order(tmp_path: Path) -> None:
    skills = tuple(_skill(tmp_path, name) for name in ("zeta", "alpha", "mid"))
    forward = build_catalog(skills, settings={}, max_tokens=2000)
    backward = build_catalog(skills[::-1], settings={}, max_tokens=2000)
    assert forward.text == backward.text
    assert [entry.skill.name for entry in forward.entries] == ["alpha", "mid", "zeta"]


def test_modes_name_only_manual_and_disabled(tmp_path: Path) -> None:
    skills = tuple(_skill(tmp_path, name, f"{name} description.") for name in ("a", "b", "c", "d"))
    catalog = build_catalog(
        skills, settings={"b": "name-only", "c": "manual"}, disabled=frozenset({"d"}), max_tokens=2000,
    )
    states = {entry.skill.name: entry.state for entry in catalog.entries}
    assert states == {"a": "full", "b": "name-only", "c": "manual", "d": "off"}
    assert f"- b (file: {skills[1].path})" in catalog.text
    assert "- c" not in catalog.text and "- d" not in catalog.text
    assert {entry.skill.name: entry.tokens for entry in catalog.entries}["c"] == 0


def test_frontmatter_invocation_manual_keeps_a_skill_out_of_the_catalog(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _skill(root, "quiet", extra="invocation: manual\n")
    _skill(root, "loud")
    found = discover_skills(tmp_path, SkillsConfig(roots=[root]))
    states = {entry.skill.name: entry.state for entry in found.catalog.entries if entry.skill.origin == "configured"}
    assert states == {"quiet": "manual", "loud": "full"}
    # An explicit setting beats the front matter.
    found = discover_skills(tmp_path, SkillsConfig(roots=[root], settings={"quiet": "on"}))
    assert "- quiet:" in found.catalog.text


def test_budget_drops_the_longest_descriptions_first_then_the_last_names(tmp_path: Path) -> None:
    short = _skill(tmp_path, "short", "tiny")
    long = _skill(tmp_path, "long", "y" * 150)
    skills = (short, long)
    full = build_catalog(skills, settings={}, max_tokens=2000)
    assert full.notices == ()
    budget = full.tokens - 10
    trimmed = build_catalog(skills, settings={}, max_tokens=budget)
    states = {entry.skill.name: entry.state for entry in trimmed.entries}
    assert states == {"short": "full", "long": "name-only"}
    assert trimmed.tokens <= budget
    assert "description left out" in trimmed.notices[0].message
    tiny = build_catalog(skills, settings={}, max_tokens=trimmed.tokens - 5)
    assert {entry.state for entry in tiny.entries} <= {"name-only", "omitted"}
    assert tiny.tokens <= trimmed.tokens - 5


def test_catalog_prefix_is_stable_when_an_unrelated_skill_is_trimmed(tmp_path: Path) -> None:
    skills = tuple(_skill(tmp_path, f"s{index:02d}", "d" * 120) for index in range(20))
    first = build_catalog(skills, settings={}, max_tokens=400)
    again = build_catalog(skills, settings={}, max_tokens=400)
    assert first.text == again.text and first.tokens <= 400
    assert any(entry.state == "omitted" for entry in first.entries)
