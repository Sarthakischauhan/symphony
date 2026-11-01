"""Finding plugins across roots, shadowing, non-fatal errors, and how an agent uses the result."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent import CodingAgent
from coding_agent.addons.plugins import install_plugin, resolve_plugins, set_enabled
from coding_agent.config import symphony_dir
from coding_agent.protocols.stdio import commands as stdio_commands
from extension_fixtures import addon_plugin_tree, plugin_tree, write_json
from scripted_registry import ScriptedRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    (path / ".git").mkdir(parents=True)
    return path


def _agent(workspace: Path) -> CodingAgent:
    return CodingAgent(registry=ScriptedRegistry({}), model_id="fake:test", workspace=workspace)  # type: ignore[arg-type]


def test_plugins_are_found_in_project_user_and_installed_places(tmp_path: Path, workspace: Path) -> None:
    plugin_tree(workspace / ".symphony" / "plugins" / "p1", "p1")
    plugin_tree(symphony_dir() / "plugins" / "p2", "p2")
    install_plugin(str(plugin_tree(tmp_path / "src", "p3")), cwd=tmp_path)
    found = resolve_plugins(workspace)
    assert {(item.name, item.scope) for item in found.plugins} == {("p1", "project"), ("p2", "user"), ("p3", "installed")}
    assert found.diagnostics == ()


def test_reserved_and_hidden_directories_are_not_plugins(workspace: Path) -> None:
    plugins = symphony_dir() / "plugins"
    for name in ("cache", "marketplaces", ".staging-x"):
        plugin_tree(plugins / name, "ghost")
    assert resolve_plugins(workspace).plugins == ()


def test_project_wins_a_name_and_the_shadowed_copy_is_a_notice(tmp_path: Path, workspace: Path) -> None:
    plugin_tree(workspace / ".symphony" / "plugins" / "dup", "dup")
    install_plugin(str(plugin_tree(tmp_path / "src", "dup", version="9.9.9")), cwd=tmp_path)
    found = resolve_plugins(workspace)
    assert [(item.name, item.scope) for item in found.plugins] == [("dup", "project")]
    assert [(item.level, "shadowed" in item.message) for item in found.diagnostics] == [("notice", True)]


def test_a_broken_plugin_is_a_diagnostic_and_the_rest_still_load(workspace: Path) -> None:
    plugin_tree(workspace / ".symphony" / "plugins" / "good", "good")
    write_json(workspace / ".symphony" / "plugins" / "bad" / "plugin.json", {"name": "bad name"})
    write_json(workspace / ".symphony" / "plugins" / "escape" / "plugin.json", {"name": "escape", "skills": "./missing/"})
    found = resolve_plugins(workspace)
    assert {item.name for item in found.plugins} == {"good", "escape"}
    assert [item.level for item in found.diagnostics] == ["error", "error"]
    assert any("bad" in item.source for item in found.diagnostics)
    assert any("missing" in item.message for item in found.diagnostics)


def test_project_plugin_addon_loads_with_its_skills(workspace: Path) -> None:
    addon_plugin_tree(workspace / ".symphony" / "plugins" / "coded", "coded")
    found = resolve_plugins(workspace)
    plugin = found.find("coded")
    assert plugin.runs_addon and found.addon_roots == (plugin.addon_root,) and len(found.skill_sources) == 1
    set_enabled("coded", False, workspace)
    assert resolve_plugins(workspace).addon_roots == ()


def test_find_reports_unknown_and_ambiguous_names(tmp_path: Path, workspace: Path) -> None:
    plugin_tree(workspace / ".symphony" / "plugins" / "x", "x")
    found = resolve_plugins(workspace)
    with pytest.raises(ValueError, match="no plugin named"):
        found.find("nope")
    assert found.find("x").name == "x" and found.find(found.plugins[0].key) is found.plugins[0]


def test_an_agent_lists_plugin_skills_with_paths_in_its_prompt(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(plugin_tree(tmp_path / "src", "demo", skills=("alpha", "beta"))), cwd=tmp_path)
    agent = _agent(workspace)
    path = next(item.path for item in agent.skill_registry.skills if item.name == "demo:alpha")
    assert f"- demo:alpha: alpha from demo. (file: {path})" in agent.harness.system_prompt
    assert path.is_absolute() and path.read_text().startswith("---")


def test_an_enabled_plugin_addon_loads_and_a_disabled_one_does_not(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(addon_plugin_tree(tmp_path / "coded")), cwd=tmp_path)
    agent = _agent(workspace)
    agent.reload_extensions()
    assert asyncio.run(stdio_commands.execute(agent, "/hello world")) == "hello world"
    set_enabled("coded", False, workspace)
    agent.reload_extensions()
    assert agent.user_addons.surface.command("hello") is None
    assert "demo:alpha" not in agent.harness.system_prompt


def test_a_disabled_plugin_is_shown_with_its_reason_not_raised(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(addon_plugin_tree(tmp_path / "coded")), cwd=tmp_path)
    set_enabled("coded", False, workspace)
    agent = _agent(workspace)
    text = asyncio.run(stdio_commands.execute(agent, "/installed"))
    assert "coded" in text and "addon not loaded: plugin disabled" in text
    agent.reload_extensions()
    assert "disabled" in asyncio.run(stdio_commands.execute(agent, "/installed"))


def test_broken_plugins_and_skills_never_stop_the_agent_and_show_in_installed(workspace: Path) -> None:
    write_json(workspace / ".symphony" / "plugins" / "bad" / "plugin.json", {"name": "bad name"})
    broken = workspace / ".agents" / "skills" / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text("no front matter")
    agent = _agent(workspace)
    text = asyncio.run(stdio_commands.execute(agent, "/installed"))
    assert "Notices (2)" in text and "bad" in text and "broken" in text
    assert [item.level for item in agent.extension_diagnostics] == ["error", "error"]


def test_plugins_disabled_in_config_load_nothing(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(plugin_tree(tmp_path / "src", "demo")), cwd=tmp_path)
    agent = _agent(workspace)
    assert [item.name for item in agent.plugins.plugins] == ["demo"]
    agent.config.plugins.enabled = False
    agent.discover_extensions()
    assert agent.plugins.plugins == () and "demo:alpha" not in {s.name for s in agent.skill_registry.skills}
