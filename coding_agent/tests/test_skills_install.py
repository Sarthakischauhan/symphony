"""``skills add|update|remove`` and the per-skill settings that change the catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent.addons.skills import (
    add_skills,
    discover_skills,
    remove_skill,
    set_skill_enabled,
    set_skill_mode,
    update_skills,
)
from coding_agent.addons.skills.install import PROVENANCE
from coding_agent.config import CodingAgentConfig, ensure_spawn_settings, symphony_dir
from extension_fixtures import commit_all, git, write_skill


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    (path / ".git").mkdir(parents=True)
    return path


def test_add_a_single_skill_from_a_path_copies_it_with_provenance(tmp_path: Path, workspace: Path) -> None:
    write_skill(tmp_path / "src" / "my-skill", "my-skill")
    added = add_skills(str(tmp_path / "src" / "my-skill"), workspace=workspace, cwd=tmp_path)
    assert [(item.name, item.scope, item.path) for item in added] == [("my-skill", "user", symphony_dir() / "skills" / "my-skill")]
    provenance = json.loads((added[0].path / PROVENANCE).read_text())
    assert provenance["source"]["kind"] == "local" and (added[0].path / "SKILL.md").is_file()


def test_the_installed_dir_is_named_by_the_skill_not_the_source_folder(tmp_path: Path, workspace: Path) -> None:
    write_skill(tmp_path / "whatever", "real-name")
    assert add_skills(str(tmp_path / "whatever"), workspace=workspace, cwd=tmp_path)[0].path.name == "real-name"


def test_add_a_collection_from_git_with_ref_and_subpath(tmp_path: Path, workspace: Path) -> None:
    repo = tmp_path / "repo"
    write_skill(repo / "skills" / "one", "one")
    write_skill(repo / "skills" / "two", "two")
    write_skill(repo / "other" / "three", "three")
    commit_all(repo)
    added = add_skills(repo.as_uri(), workspace=workspace, cwd=tmp_path, subdir="skills")
    assert sorted(item.name for item in added) == ["one", "two"]
    one = json.loads((symphony_dir() / "skills" / "one" / PROVENANCE).read_text())
    assert one["source"]["subdir"] == "skills/one" and len(one["revision"]) == 40


def test_project_flag_installs_under_the_git_root_agents_skills(tmp_path: Path, workspace: Path) -> None:
    write_skill(tmp_path / "s", "proj-skill")
    nested = workspace / "pkg"
    nested.mkdir()
    added = add_skills(str(tmp_path / "s"), workspace=nested, cwd=tmp_path, project=True)
    assert added[0].path == workspace.resolve() / ".agents" / "skills" / "proj-skill" and added[0].scope == "project"


def test_add_refuses_overwrites_and_empty_sources_and_changes_nothing(tmp_path: Path, workspace: Path) -> None:
    write_skill(tmp_path / "a", "dup")
    add_skills(str(tmp_path / "a"), workspace=workspace, cwd=tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        add_skills(str(tmp_path / "a"), workspace=workspace, cwd=tmp_path)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="no SKILL.md"):
        add_skills(str(tmp_path / "empty"), workspace=workspace, cwd=tmp_path)
    write_skill(tmp_path / "coll" / "fresh", "fresh")
    write_skill(tmp_path / "coll" / "dup", "dup")
    with pytest.raises(ValueError, match="already exists"):
        add_skills(str(tmp_path / "coll"), workspace=workspace, cwd=tmp_path)
    assert not (symphony_dir() / "skills" / "fresh").exists()


def test_an_invalid_skill_is_rejected_before_anything_is_copied(tmp_path: Path, workspace: Path) -> None:
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "SKILL.md").write_text("no front matter")
    with pytest.raises(ValueError):
        add_skills(str(tmp_path / "bad"), workspace=workspace, cwd=tmp_path)
    assert not (symphony_dir() / "skills").exists()


def test_update_fetches_the_new_commit_and_reports_unchanged(tmp_path: Path, workspace: Path) -> None:
    repo = tmp_path / "repo"
    write_skill(repo / "x", "x", "old")
    first = commit_all(repo)
    add_skills(repo.as_uri(), workspace=workspace, cwd=tmp_path)
    same = update_skills("x", workspace=workspace)[0]
    assert same.before == same.after == first[:12]
    write_skill(repo / "x", "x", "new description")
    second = commit_all(repo)
    result = update_skills(None, workspace=workspace)[0]
    assert (result.before, result.after) == (first[:12], second[:12])
    assert "new description" in (symphony_dir() / "skills" / "x" / "SKILL.md").read_text()
    with pytest.raises(ValueError, match="no skill named"):
        update_skills("ghost", workspace=workspace)


def test_update_failure_keeps_the_installed_skill(tmp_path: Path, workspace: Path) -> None:
    repo = tmp_path / "repo"
    write_skill(repo, "x")
    commit_all(repo)
    add_skills(repo.as_uri(), workspace=workspace, cwd=tmp_path)
    git(repo, "rm", "-q", "SKILL.md")
    commit_all(repo, "break")
    result = update_skills("x", workspace=workspace)[0]
    assert result.error and (symphony_dir() / "skills" / "x" / "SKILL.md").is_file()


def test_remove_deletes_only_what_add_installed(tmp_path: Path, workspace: Path) -> None:
    write_skill(tmp_path / "s", "mine")
    add_skills(str(tmp_path / "s"), workspace=workspace, cwd=tmp_path)
    write_skill(symphony_dir() / "skills" / "handmade", "handmade")
    assert remove_skill("mine", workspace=workspace) == symphony_dir() / "skills" / "mine"
    assert not (symphony_dir() / "skills" / "mine").exists()
    with pytest.raises(ValueError, match="not installed by"):
        remove_skill("handmade", workspace=workspace)
    assert (symphony_dir() / "skills" / "handmade").is_dir()


def test_enable_disable_and_mode_are_saved_and_change_the_catalog(workspace: Path) -> None:
    write_skill(symphony_dir() / "skills" / "a", "a", "alpha skill")
    write_skill(symphony_dir() / "skills" / "b", "b", "beta skill")
    write_skill(symphony_dir() / "skills" / "c", "c", "gamma skill")
    set_skill_enabled("a", False, workspace=workspace)
    set_skill_mode("b", "name-only", workspace=workspace)
    set_skill_mode("c", "manual", workspace=workspace)
    config = ensure_spawn_settings(workspace)
    assert (config.skills.disabled, config.skills.settings) == (["a"], {"b": "name-only", "c": "manual"})
    catalog = discover_skills(workspace, config.skills).catalog
    states = {entry.skill.name: entry.state for entry in catalog.entries}
    assert (states["a"], states["b"], states["c"]) == ("off", "name-only", "manual")
    assert "- b (file:" in catalog.text and "alpha" not in catalog.text and "gamma" not in catalog.text
    set_skill_enabled("a", True, workspace=workspace)
    set_skill_mode("b", None, workspace=workspace)
    config = ensure_spawn_settings(workspace)
    assert (config.skills.disabled, config.skills.settings) == ([], {"c": "manual"})


def test_the_default_catalog_budget_is_6000_tokens(workspace: Path) -> None:
    assert CodingAgentConfig().skills.max_context_tokens == 6000
