"""Tests for scoped plugin and skill discovery."""

from pathlib import Path

from coding_agent.plugins.manager import PluginManager


def _write_plugin(root: Path, plugin_id: str = "demo") -> Path:
    plugin = root / plugin_id
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        '{"schema_version": 1, "id": "demo", "skills": ["skills"]}',
        encoding="utf-8",
    )
    (plugin / "skills").mkdir()
    return plugin


def test_plugin_discovery_finds_user_and_workspace_scopes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    user_plugin = _write_plugin(tmp_path / "home" / ".symphony" / "plugins", "user-plugin")
    workspace_plugin = _write_plugin(workspace / ".symphony" / "plugins", "workspace-plugin")

    entries = PluginManager(workspace).discover()

    assert {entry.path for entry in entries} == {user_plugin.resolve(), workspace_plugin.resolve()}


def test_plugin_discovery_ignores_directories_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    (workspace / ".symphony" / "plugins" / "not-a-plugin").mkdir(parents=True)

    assert PluginManager(workspace).discover() == ()
