"""Tests for scoped plugin discovery, manifest metadata, and the /extensions modal."""

import asyncio
import json
from pathlib import Path

from textual.app import App
from textual.widgets import Static

from coding_agent.addons.skills.args import ExtensionArg
from coding_agent.addons.plugins import LoadedPlugin, PluginConfig
from coding_agent.addons.plugins.manager import PluginManager, bundled_plugins_root
from coding_agent.addons.skills.registry import SkillRegistry
from coding_agent.addons.skills import Skill
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


def test_shipped_reliability_plugin_loads_without_code(tmp_path):
    root = bundled_plugins_root() / "reliability"
    result = PluginManager(tmp_path).load([PluginConfig(path=root)])
    assert result.diagnostics == () and result.addons == []
    assert result.plugins == (
        LoadedPlugin(
            "reliability",
            "Shipped instructions that keep a coding task complete: a failing test first, then the code, the tests, and a fresh verification run.",
            root.resolve(),
            True,
        ),
    )
    registry, diagnostics = SkillRegistry.discover(result.skill_roots)
    assert diagnostics == ()
    assert {skill.name for skill in registry.skills} == {"finish-the-task", "test-first"}


def test_user_plugin_replaces_shipped_plugin_with_the_same_id(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    shipped = bundled_plugins_root() / "reliability"
    user = tmp_path / "home" / ".symphony" / "plugins" / "reliability"
    user.mkdir(parents=True)
    (user / "plugin.json").write_text(
        '{"schema_version": 1, "id": "reliability", "description": "Local replacement.", "skills": ["skills"]}',
        encoding="utf-8",
    )
    (user / "skills" / "test-first").mkdir(parents=True)
    (user / "skills" / "test-first" / "SKILL.md").write_text(
        "---\nname: test-first\ndescription: Replaced.\n---\nLOCAL\n",
        encoding="utf-8",
    )
    entries = PluginManager(tmp_path / "repo").discover()
    result = PluginManager(tmp_path / "repo").load(entries)
    assert result.diagnostics == ()
    assert [plugin.plugin_id for plugin in result.plugins] == ["reliability"]
    assert result.plugins[0].root == user.resolve()
    registry, diagnostics = SkillRegistry.discover(result.skill_roots)
    assert diagnostics == ()
    assert registry.get("plugin/reliability/test-first").description == "Replaced."
    assert "finish-the-task" not in {skill.name for skill in registry.skills}
    assert shipped.is_dir()


def test_plugin_discovery_finds_user_scope_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    user_plugin = _write_plugin(tmp_path / "home" / ".symphony" / "plugins", "user-plugin")
    _write_plugin(workspace / ".symphony" / "plugins", "workspace-plugin")

    entries = PluginManager(workspace).discover()

    assert user_plugin.resolve() in {entry.path for entry in entries}
    assert not any(entry.path.is_relative_to(workspace.resolve()) for entry in entries)


def test_plugin_discovery_ignores_directories_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    workspace = tmp_path / "repo"
    (workspace / ".symphony" / "plugins" / "not-a-plugin").mkdir(parents=True)

    assert all(entry.path.is_relative_to(bundled_plugins_root().resolve()) for entry in PluginManager(workspace).discover())


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


def test_plugin_with_empty_description_loads(tmp_path):
    plain = _manifest(tmp_path / "plain", id="plain", description="")
    result = PluginManager(tmp_path).load([PluginConfig(path=plain)])
    assert result.diagnostics == ()
    assert result.plugins == (LoadedPlugin("plain", "", plain.resolve(), True),)


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


def test_extensions_modal_renders_markup_like_plugin_paths_literally(tmp_path):
    plugin = LoadedPlugin("odd[/]id", "", tmp_path / "odd[/]root", True)

    async def _run() -> list[str]:
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(ExtensionsModal((), (plugin,)))
            await pilot.pause()
            return [str(widget.render()) for widget in app.screen.query(Static)]

    texts = asyncio.run(_run())
    assert "odd[/]id" in texts and str(tmp_path / "odd[/]root") in texts
