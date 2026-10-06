"""Skills stay a short catalog in the prompt; bodies load on demand. Read-only tools batch."""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent.agent import CodingAgent
from coding_agent.addons.skills.models import CATALOG_DESCRIPTION_CHARS, Skill
from coding_agent.addons.skills.registry import SkillRegistry
from coding_agent.addons.skills.tool import SkillTool
from coding_agent.tools import BashTool, MemoryGetTool, MemorySearchTool, MemoryTool


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills" / "orient"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: orient\ndescription: Map owners first.\n---\nBODY-SENTINEL: read the call graph.\n",
        encoding="utf-8",
    )
    (root / "references" / "map.md").write_text("REFERENCE-SENTINEL\n", encoding="utf-8")
    return root


class _Registry:
    async def stream(self, *args, **kwargs):  # pragma: no cover - never called
        if False:
            yield None


def test_system_prompt_lists_ids_not_bodies_and_skill_tool_is_registered(tmp_path: Path, monkeypatch) -> None:
    _skill_root(tmp_path)
    monkeypatch.setattr("coding_agent.agent.bundled_skills_root", lambda: tmp_path / "skills")
    agent = CodingAgent(registry=_Registry(), model_id="test:model", workspace=tmp_path)  # type: ignore[arg-type]
    prompt = agent.harness.system_prompt
    assert "- bundled/orient: Map owners first." in prompt
    assert "BODY-SENTINEL" not in prompt
    assert "SKILL.md:" not in prompt
    assert "skill" in agent.harness.tools
    result = asyncio.run(agent.harness.tools["skill"].execute(sink=None, args={"skill_id": "bundled/orient"}))
    assert "BODY-SENTINEL" in result
    assert "references/map.md" in result


def test_skill_tool_reads_resources_and_refuses_escapes(tmp_path: Path) -> None:
    _skill_root(tmp_path)
    registry, diagnostics = SkillRegistry.discover([("user", tmp_path / "skills")])
    assert diagnostics == ()
    tool = SkillTool(tmp_path, registry=registry)
    assert tool.parallel is True
    assert tool.run("user/orient", resource="references/map.md") == "REFERENCE-SENTINEL\n"
    assert tool.run("user/orient", resource="../../outside.txt").startswith("error:")
    assert tool.run("user/orient", resource="/etc/passwd").startswith("error:")
    assert tool.run("user/missing").startswith("error: Unknown skill id")


def test_catalog_line_is_short(tmp_path: Path) -> None:
    skill = Skill("user/long", "long", "x" * 500, tmp_path, "user")
    line = skill.catalog_line()
    assert len(line) <= len("- user/long: ") + CATALOG_DESCRIPTION_CHARS
    assert str(tmp_path) not in line


def test_read_only_memory_tools_are_parallel_and_writes_stay_serial(tmp_path: Path) -> None:
    assert MemorySearchTool(tmp_path).parallel is True
    assert MemoryGetTool(tmp_path).parallel is True
    assert MemoryTool(tmp_path).parallel is False
    assert BashTool(str(tmp_path)).parallel is False


def test_bash_description_steers_toward_pipelines_and_scripts() -> None:
    description = BashTool.description
    assert "one well-built command usually beats many small tool calls" in description
    assert "|" in description and "<<'EOF'" in description
