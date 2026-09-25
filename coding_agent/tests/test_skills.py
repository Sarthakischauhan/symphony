"""Skill and plugin front matter loads name, description, and args."""

from pathlib import Path

import pytest

from coding_agent.skills.frontmatter import parse_args, parse_skill_front_matter
from coding_agent.plugins.manager import PluginManager
from coding_agent.skills.registry import SkillRegistry, bundled_skills_root


def _write_skill(root: Path, name: str, front: str, body: str = "Do the thing.\n") -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")


def test_bundled_skills_load_name_description_and_args():
    registry, diagnostics = SkillRegistry.discover([("bundled", bundled_skills_root())])
    assert diagnostics == ()
    debug = registry.get("bundled/systematic-debug")
    assert debug.name == "systematic-debug"
    assert "Reproduce" in debug.description
    assert [arg.name for arg in debug.args] == ["repro", "hypothesis"]
    assert debug.args[0].required is True
    assert debug.args[0].type == "string"
    assert "repro: string required" in debug.catalog_line()


def test_folded_description_and_enum_arg(tmp_path: Path):
    _write_skill(
        tmp_path,
        "orient",
        """
name: orient
description: >
  Folded line
  still one description.
args:
  - name: depth
    type: enum
    enum: [sketch, thorough]
    description: How far to map.
    default: sketch
""".strip(),
    )
    registry, diagnostics = SkillRegistry.discover([("workspace", tmp_path)])
    assert diagnostics == ()
    skill = registry.get("workspace/orient")
    assert skill.description == "Folded line still one description."
    assert skill.args[0].options == ("sketch", "thorough")
    assert skill.args[0].default == "sketch"


def test_malformed_args_are_skipped_and_valid_skills_remain(tmp_path: Path):
    _write_skill(
        tmp_path,
        "bad-enum",
        """
name: bad-enum
description: Missing enum options.
args:
  - name: mode
    type: enum
    description: Mode.
""".strip(),
    )
    _write_skill(
        tmp_path,
        "ok-skill",
        "name: ok-skill\ndescription: This one still loads.\nargs: []",
    )
    registry, diagnostics = SkillRegistry.discover([("workspace", tmp_path)])
    assert registry.get("workspace/ok-skill").args == ()
    assert len(diagnostics) == 1
    assert "bad-enum" in diagnostics[0].source


def test_duplicate_argument_names_are_rejected():
    with pytest.raises(ValueError, match="duplicate argument name"):
        parse_skill_front_matter(
            "name: demo\ndescription: Has two of the same arg.\n"
            "args:\n  - {name: repro, type: string, description: One.}\n"
            "  - {name: repro, type: string, description: Two.}\n"
        )


def test_plugin_manifest_loads_description_and_args(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    plugin = tmp_path / "home" / ".symphony" / "plugins" / "search"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        """
        {
          "schema_version": 1,
          "id": "search",
          "description": "Search before opening files.",
          "args": [
            {"name": "query", "type": "string", "description": "Text to find.", "required": true}
          ],
          "skills": []
        }
        """,
        encoding="utf-8",
    )
    manager = PluginManager(tmp_path / "repo")
    addons, roots, diagnostics = manager.load(manager.discover())
    assert addons == []
    assert roots == []
    assert diagnostics == ()
    loaded = manager.loaded[0]
    assert loaded.plugin_id == "search"
    assert loaded.description == "Search before opening files."
    assert loaded.args[0].name == "query"
    assert loaded.args[0].required is True


def test_parse_args_rejects_a_non_list():
    with pytest.raises(ValueError, match="args must be a list"):
        parse_args("query")
