"""Tests for scoped plugin discovery, manifest metadata, and the /extensions modal."""

import asyncio
import json
from pathlib import Path

from textual.app import App
from textual.widgets import Static

from coding_agent.extension_args import ExtensionArg
from coding_agent.plugins import LoadedPlugin, PluginConfig
from coding_agent.plugins.manager import PluginManager
from coding_agent.skills import Skill
from coding_agent.tui.screens.extensions import ExtensionsModal


def _write_plugin(root: Path, plugin_id: str = "demo") -> Path:
    plugin = root / plugin_id
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        '{"schema_version": 1, "id": "demo", "skills": ["skills"]}',
        encoding="utf-8",
    )
    (plugin / "skills").mkdir()
    return plugin


def test_plugin_discovery_finds_user_scope_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    user_plugin = _write_plugin(tmp_path / "home" / ".symphony" / "plugins", "user-plugin")
    _write_plugin(workspace / ".symphony" / "plugins", "workspace-plugin")

    entries = PluginManager(workspace).discover()

    assert {entry.path for entry in entries} == {user_plugin.resolve()}


def test_plugin_discovery_ignores_directories_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    (workspace / ".symphony" / "plugins" / "not-a-plugin").mkdir(parents=True)

    assert PluginManager(workspace).discover() == ()


def _manifest(root: Path, **fields: object) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"schema_version": 1, **fields}), encoding="utf-8")
    return root


def test_plugin_load_returns_description_for_enabled_and_disabled_manifests(tmp_path):
    search = _manifest(tmp_path / "search", id="search", description="Search  before\nopening files.")
    idle = _manifest(tmp_path / "idle", id="idle")
    result = PluginManager(tmp_path).load([PluginConfig(path=search), PluginConfig(path=idle, enabled=False)])
    assert result.diagnostics == () and result.addons == [] and result.skill_roots == []
    assert result.plugins == (
        LoadedPlugin("search", "Search before opening files.", search.resolve(), True),
        LoadedPlugin("idle", "", idle.resolve(), False),
    )


def test_invalid_plugin_metadata_is_a_diagnostic(tmp_path):
    bad = _manifest(tmp_path / "bad", id="bad", description=42)
    result = PluginManager(tmp_path).load([PluginConfig(path=bad)])
    assert result.plugins == ()
    assert len(result.diagnostics) == 1 and "description" in result.diagnostics[0].message


def test_extensions_modal_renders_skill_args_and_plugin_states(tmp_path):
    depth = ExtensionArg(name="depth", type="enum", enum=["sketch", "thorough"], description="D.", default="sketch")
    skill = Skill("user/orient", "orient", "Map owners first.", tmp_path, "user", (depth,))
    plugins = (
        LoadedPlugin("search", "Search before opening files.", tmp_path / "search", True),
        LoadedPlugin("idle", "", tmp_path / "idle", False),
    )

    async def _run() -> list[str]:
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(ExtensionsModal((skill,), plugins))
            await pilot.pause()
            return [str(widget.render()) for widget in app.screen.query(Static)]

    texts = asyncio.run(_run())
    assert "args  depth: enum[sketch|thorough]=sketch" in texts
    assert {"search", "ENABLED", "Search before opening files.", "idle", "DISABLED"} <= set(texts)
    assert "3 total" in texts
