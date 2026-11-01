"""Installing plugins from a local Claude-format marketplace, direct sources and git; state, update, remove."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent.addons.plugins import (
    add_marketplace,
    install_plugin,
    list_marketplaces,
    remove_marketplace,
    remove_plugin,
    resolve_plugins,
    set_enabled,
    update_marketplaces,
    update_plugins,
)
from coding_agent.addons.plugins.state import load_state, plugins_dir
from extension_fixtures import addon_plugin_tree, claude_marketplace, commit_all, plugin_tree, write_json


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def test_real_claude_format_plugin_installs_from_a_local_marketplace(tmp_path: Path, workspace: Path) -> None:
    market = claude_marketplace(tmp_path / "market", "acme", ("demo", "other"))
    record, manifest = add_marketplace(str(market), cwd=tmp_path)
    assert (record.name, [item.name for item in manifest.plugins]) == ("acme", ["demo", "other"])
    installed = install_plugin("demo@acme", cwd=tmp_path)
    assert installed.key == "demo@acme" and installed.version == "1.0.0"
    root = plugins_dir() / "cache" / "acme" / "demo" / "1.0.0"
    assert (root / "skills" / "alpha" / "SKILL.md").is_file() and installed.path == "cache/acme/demo/1.0.0"
    found = resolve_plugins(workspace)
    plugin = found.find("demo")
    assert (plugin.scope, plugin.enabled, plugin.addon_root, plugin.skill_count) == ("installed", True, None, 1)
    assert found.skill_sources[0].namespace == "demo" and found.skill_sources[0].path == root.resolve() / "skills"


def test_marketplace_is_a_staged_copy_and_survives_the_original_moving(tmp_path: Path) -> None:
    market = claude_marketplace(tmp_path / "market", "acme")
    add_marketplace(str(market), cwd=tmp_path)
    (market / ".claude-plugin" / "marketplace.json").unlink()
    assert install_plugin("demo@acme", cwd=tmp_path).name == "demo"
    assert [record.name for record, _ in list_marketplaces()] == ["acme"]
    assert update_marketplaces("acme")[0][1].startswith("failed")


def test_installing_from_an_unknown_marketplace_or_plugin_explains(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not added"):
        install_plugin("demo@nowhere", cwd=tmp_path)
    add_marketplace(str(claude_marketplace(tmp_path / "market", "acme")), cwd=tmp_path)
    with pytest.raises(ValueError, match="lists: demo"):
        install_plugin("ghost@acme", cwd=tmp_path)
    assert not (plugins_dir() / "cache" / "acme" / "ghost").exists()


def test_a_marketplace_name_cannot_be_taken_over_by_another_source(tmp_path: Path) -> None:
    add_marketplace(str(claude_marketplace(tmp_path / "one", "acme")), cwd=tmp_path)
    with pytest.raises(ValueError, match="already added"):
        add_marketplace(str(claude_marketplace(tmp_path / "two", "acme")), cwd=tmp_path)
    assert remove_marketplace("acme") == 0
    add_marketplace(str(claude_marketplace(tmp_path / "two", "acme")), cwd=tmp_path)


def test_direct_install_from_a_path_a_subdirectory_and_git(tmp_path: Path) -> None:
    plugin_tree(tmp_path / "plain", "plain")
    assert install_plugin(str(tmp_path / "plain"), cwd=tmp_path).key == "plain@direct"
    nested = tmp_path / "mono"
    plugin_tree(nested / "pkgs" / "inner", "inner")
    assert install_plugin(str(nested), cwd=tmp_path, subdir="pkgs/inner").name == "inner"
    repo = tmp_path / "repo"
    plugin_tree(repo, "gitted")
    sha = commit_all(repo)
    record = install_plugin(repo.as_uri(), cwd=tmp_path)
    assert (record.name, record.revision) == ("gitted", sha)


def test_a_plugin_that_fails_validation_leaves_nothing_behind(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    write_json(broken / "plugin.json", {"name": "bad name"})
    with pytest.raises(ValueError, match="name"):
        install_plugin(str(broken), cwd=tmp_path)
    assert load_state().plugins == {} and not (plugins_dir() / "cache").exists()
    assert [path.name for path in plugins_dir().iterdir()] == []


def test_install_copies_files_and_does_not_run_addon_code(tmp_path: Path, workspace: Path) -> None:
    source = addon_plugin_tree(tmp_path / "coded")
    (source / "addons" / "hello" / "addon.py").write_text(f"open({str(tmp_path / 'ran')!r}, 'w').write('x')\n")
    install_plugin(str(source), cwd=tmp_path)
    plugin = resolve_plugins(workspace).find("coded")
    assert plugin.runs_addon and plugin.addon_root is not None
    assert "addon loads while this plugin is enabled" in plugin.addon_note
    assert resolve_plugins(workspace).addon_roots == (plugin.addon_root,)
    assert not (tmp_path / "ran").exists()


def test_disabling_a_plugin_stops_its_addon_and_skills(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(addon_plugin_tree(tmp_path / "coded")), cwd=tmp_path)
    plugin = resolve_plugins(workspace).find("coded")
    assert plugin.runs_addon and resolve_plugins(workspace).addon_roots == (plugin.addon_root,)
    set_enabled("coded", False, workspace)
    disabled = resolve_plugins(workspace).find("coded")
    assert not disabled.runs_addon and "plugin disabled" in disabled.addon_note
    assert resolve_plugins(workspace).addon_roots == () and resolve_plugins(workspace).skill_sources == ()
    set_enabled("coded", True, workspace)
    assert resolve_plugins(workspace).find("coded").runs_addon


def test_a_plugin_without_an_addon_still_loads_its_skills(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(plugin_tree(tmp_path / "plain", "plain")), cwd=tmp_path)
    plugin = resolve_plugins(workspace).find("plain")
    assert plugin.addon_root is None and plugin.addon_note == "" and plugin.skill_count == 1


def test_update_keeps_the_enabled_state(tmp_path: Path, workspace: Path) -> None:
    source = addon_plugin_tree(tmp_path / "coded")
    install_plugin(str(source), cwd=tmp_path)
    set_enabled("coded", False, workspace)
    assert update_plugins("coded")[0].before == "1.0.0"
    assert resolve_plugins(workspace).find("coded").enabled is False
    (source / "addons" / "hello" / "addon.py").write_text("# new code\n")
    update_plugins(None)
    updated = resolve_plugins(workspace).find("coded")
    assert updated.enabled is False and not updated.runs_addon


def test_update_moves_to_the_new_version_and_removes_the_old_directory(tmp_path: Path) -> None:
    market = claude_marketplace(tmp_path / "market", "acme")
    add_marketplace(str(market), cwd=tmp_path)
    install_plugin("demo@acme", cwd=tmp_path)
    plugin_tree(market / "plugins" / "demo", "demo", version="2.0.0")
    write_json(market / ".claude-plugin" / "marketplace.json", {"name": "acme", "plugins": [{"name": "demo", "source": "./plugins/demo", "version": "2.0.0"}]})
    assert update_marketplaces()[0][1].startswith("updated")
    result = update_plugins("demo")[0]
    assert (result.before, result.after, result.error) == ("1.0.0", "2.0.0", "")
    assert sorted(path.name for path in (plugins_dir() / "cache" / "acme" / "demo").iterdir()) == ["2.0.0"]


def test_update_reports_a_failure_and_keeps_the_installed_copy(tmp_path: Path) -> None:
    source = plugin_tree(tmp_path / "plain", "plain")
    install_plugin(str(source), cwd=tmp_path)
    (source / ".claude-plugin" / "plugin.json").write_text("{broken")
    result = update_plugins(None)[0]
    assert result.error and (plugins_dir() / "cache" / "direct" / "plain" / "1.0.0" / "skills").is_dir()
    with pytest.raises(ValueError, match="no installed plugin"):
        update_plugins("ghost")


def test_git_update_picks_up_a_new_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    plugin_tree(repo, "gitted")
    first = commit_all(repo)
    install_plugin(repo.as_uri(), cwd=tmp_path)
    (repo / "NEW").write_text("x")
    second = commit_all(repo)
    update_plugins("gitted")
    assert load_state().plugins["gitted@direct"].revision == second != first


def test_remove_deletes_the_cache_and_refuses_plugins_it_did_not_install(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(plugin_tree(tmp_path / "plain", "plain")), cwd=tmp_path)
    removed = remove_plugin("plain", workspace)
    assert removed.key == "plain@direct" and not (plugins_dir() / "cache" / "direct" / "plain").exists()
    assert load_state().plugins == {}
    hand_made = plugin_tree(workspace / ".symphony" / "plugins" / "mine", "mine")
    with pytest.raises(ValueError, match="not installed by symphony"):
        remove_plugin("mine", workspace)
    assert hand_made.is_dir()


def test_state_file_is_valid_json_and_a_corrupt_one_is_a_diagnostic_not_a_crash(tmp_path: Path, workspace: Path) -> None:
    install_plugin(str(plugin_tree(tmp_path / "plain", "plain")), cwd=tmp_path)
    assert json.loads((plugins_dir() / "state.json").read_text())["plugins"]["plain@direct"]["installed"] is True
    (plugins_dir() / "state.json").write_text("{nope")
    found = resolve_plugins(workspace)
    assert found.plugins == () and "unreadable" in found.diagnostics[0].message
