"""Acceptance: Symphony installs and uses pstack, in both of its published formats.

The fixtures under ``fixtures/pstack`` are trimmed, unmodified copies of
backnotprop/pstack (Cursor format) and michael-denyer/pstack-claude (Claude
marketplace plus ``.agents/plugins``); see ``fixtures/pstack/UPSTREAM.md`` for the
commits and licenses. Each test turns them into real git repositories and installs
from ``file://`` URLs, so nothing touches the network.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from coding_agent import CodingAgent
from coding_agent.commands.cli_support import Context
from coding_agent.commands.plugins_cli import run as plugins
from coding_agent.extensions import source as sources
from coding_agent.protocols.stdio import commands as stdio_commands
from extension_fixtures import PSTACK, commit_all
from scripted_registry import ScriptedRegistry


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, Path]:
    built = {}
    for name in ("pstack", "pstack-claude"):
        shutil.copytree(PSTACK / name, tmp_path / "repos" / name)
        commit_all(tmp_path / "repos" / name)
        built[name] = tmp_path / "repos" / name
    return built


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "work").mkdir()
    return tmp_path / "work"


def _agent(workspace: Path, registry: ScriptedRegistry | None = None) -> CodingAgent:
    return CodingAgent(registry=registry or ScriptedRegistry({}), model_id="fake:test", workspace=workspace)  # type: ignore[arg-type]


def _read_turn(agent: CodingAgent, registry: ScriptedRegistry, skill: str) -> str:
    """Run a scripted turn in which the model reads ``skill``'s SKILL.md with read_file; return what it got back."""
    path = next(item.path for item in agent.skill_registry.skills if item.name == skill)
    registry.scripts["use it"] = [[("read_file", {"path": str(path)})]]
    asyncio.run(agent.run("use it"))
    follow_up = next(call for call in registry.calls if call[-1].role == "tool")
    return str(follow_up[-1].content)


def test_cursor_format_pstack_installs_from_a_git_url(repos: dict[str, Path], workspace: Path, tmp_path: Path) -> None:
    out = plugins(["add", repos["pstack"].as_uri()], Context(workspace, tmp_path))
    assert out.ok and out.changed
    assert "Installed pstack 0.15.36: 3 skills" in out.text
    assert "skipped agents: plugin-defined agents are not supported" in out.text
    assert "skipped automations: automations are not supported" in out.text


def test_claude_format_pstack_installs_from_its_marketplace(repos: dict[str, Path], workspace: Path, tmp_path: Path) -> None:
    context = Context(workspace, tmp_path)
    added = plugins(["marketplace", "add", repos["pstack-claude"].as_uri()], context)
    assert added.text == "Added marketplace pstack-claude (1 plugins: pstack)"
    out = plugins(["add", "pstack@pstack-claude"], context)
    assert out.ok and "Installed pstack 0.9.114: 3 skills" in out.text
    assert "skipped agents:" in out.text and "skipped hooks:" in out.text and "automations" not in out.text


def test_the_owner_repo_shorthand_resolves_through_github_base(repos: dict[str, Path], workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mirror = tmp_path / "gh" / "michael-denyer"
    mirror.mkdir(parents=True)
    shutil.copytree(repos["pstack-claude"], mirror / "pstack-claude.git")
    monkeypatch.setattr(sources, "GITHUB_BASE", f"{(tmp_path / 'gh').as_uri()}/")
    context = Context(workspace, tmp_path)
    assert plugins(["marketplace", "add", "michael-denyer/pstack-claude"], context).ok
    assert plugins(["add", "pstack@pstack-claude"], context).ok


def test_pstack_skills_reach_the_catalog_with_absolute_paths_and_a_turn_reads_one(
    repos: dict[str, Path], workspace: Path, tmp_path: Path,
) -> None:
    plugins(["add", repos["pstack"].as_uri()], Context(workspace, tmp_path))
    registry = ScriptedRegistry({})
    agent = _agent(workspace, registry)
    prompt = agent.harness.system_prompt
    for skill in ("no-comments", "principle-fix-root-causes", "principle-prove-it-works"):
        entry = next(item for item in agent.skills.catalog.entries if item.skill.name == f"pstack:{skill}")
        assert entry.state == "full" and entry.skill.path.is_absolute()
        assert entry.line in prompt and entry.line.endswith(f"(file: {entry.skill.path})")
    assert "read its SKILL.md at the path shown" in prompt
    body = _read_turn(agent, registry, "pstack:no-comments")
    assert "name: no-comments" in body


def test_the_claude_plugin_works_the_same_and_installed_lists_what_was_skipped(
    repos: dict[str, Path], workspace: Path, tmp_path: Path,
) -> None:
    context = Context(workspace, tmp_path)
    plugins(["marketplace", "add", repos["pstack-claude"].as_uri()], context)
    plugins(["add", "pstack@pstack-claude"], context)
    registry = ScriptedRegistry({})
    agent = _agent(workspace, registry)
    assert {"pstack:bro", "pstack:interrogate", "pstack:principle-fix-root-causes"} <= {s.name for s in agent.skill_registry.skills}
    assert "name: bro" in _read_turn(agent, registry, "pstack:bro")
    report = asyncio.run(stdio_commands.execute(agent, "/installed"))
    assert "skipped agents: plugin-defined agents are not supported" in report
    assert "skipped hooks: hooks are not supported" in report
    assert "pstack:bro" in report and "plugin:pstack" in report


def test_what_pstack_adds_beyond_skills_never_runs_or_loads(repos: dict[str, Path], workspace: Path, tmp_path: Path) -> None:
    plugins(["add", repos["pstack"].as_uri()], Context(workspace, tmp_path))
    agent = _agent(workspace)
    plugin = agent.plugins.find("pstack")
    assert plugin.addon_root is None and agent.plugins.addon_roots == ()
    assert [label for label, _ in plugin.skipped] == ["agents", "automations"]
    assert agent.user_addons.surface.slash_commands == ()
