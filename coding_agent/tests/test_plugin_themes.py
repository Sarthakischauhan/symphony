"""Plugin ``themes/`` discovery: file formats, namespacing, bad files, and what plugins expose."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from coding_agent.addons.plugins import PluginTheme, find_theme, install_plugin, resolve_plugins, set_enabled
from coding_agent.addons.plugins.themes import MAX_THEME_BYTES, discover_plugin_themes
from coding_agent.commands.installed import plugin_details
from extension_fixtures import plugin_tree, write_json

DRACULA = Path(__file__).parent / "fixtures" / "claude-themes" / "dracula"
NATIVE = '''name = "Night Owl"
base = "dark"

[colors]
accent = "#82aaff"
background = "#011627"
'''


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    (path / ".git").mkdir(parents=True)
    return path


def _themes_dir(root: Path) -> Path:
    path = root / "themes"
    path.mkdir(parents=True)
    return path


def test_the_vendored_claude_themes_plugin_is_discovered_in_the_claude_format() -> None:
    themes, diagnostics = discover_plugin_themes("dracula", DRACULA)
    assert diagnostics == ()
    assert [(item.qualified_name, item.format, item.base) for item in themes] == [
        ("dracula:Dracula", "claude", "dark"),
        ("dracula:Dracula (ANSI)", "claude", "dark-ansi"),
    ]
    assert themes[0].colors["claude"] == "rgb(255,184,108)"
    assert themes[1].colors["text"] == "ansi:white"


def test_native_toml_themes_use_the_symphony_shape_and_the_file_name_when_unnamed(tmp_path: Path) -> None:
    folder = _themes_dir(tmp_path)
    (folder / "night-owl.toml").write_text(NATIVE, encoding="utf-8")
    (folder / "solar_flare.toml").write_text('[colors]\naccent = "#ff8800"\n', encoding="utf-8")
    themes, diagnostics = discover_plugin_themes("owl", tmp_path)
    assert diagnostics == ()
    by_name = {item.name: item for item in themes}
    assert set(by_name) == {"Night Owl", "Solar Flare"}
    assert by_name["Night Owl"].format == "symphony"
    assert by_name["Night Owl"].colors == {"accent": "#82aaff", "background": "#011627"}
    assert by_name["Solar Flare"].base == "dark"


def test_a_json_theme_without_a_name_is_named_after_its_file(tmp_path: Path) -> None:
    write_json(_themes_dir(tmp_path) / "ocean-deep.json", {"base": "light", "overrides": {}})
    (theme,) = discover_plugin_themes("p", tmp_path)[0]
    assert (theme.name, theme.base) == ("Ocean Deep", "light")


def test_bad_files_are_diagnostics_and_good_ones_still_load(tmp_path: Path) -> None:
    folder = _themes_dir(tmp_path)
    write_json(folder / "good.json", {"name": "Good", "base": "dark", "overrides": {}})
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    (folder / "list.json").write_text("[1, 2]", encoding="utf-8")
    write_json(folder / "base.json", {"name": "Bad Base", "base": "sepia", "overrides": {}})
    (folder / "bad.toml").write_text("= nope", encoding="utf-8")
    (folder / "nocolors.toml").write_text('name = "None"\n', encoding="utf-8")
    (folder / "huge.json").write_text(json.dumps({"name": "Huge", "pad": "x" * MAX_THEME_BYTES}), encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    themes, diagnostics = discover_plugin_themes("p", tmp_path)
    assert [item.name for item in themes] == ["Good"]
    assert sorted(Path(item.source).name for item in diagnostics) == ["bad.toml", "base.json", "broken.json", "huge.json", "list.json", "nocolors.toml"]
    assert all(item.message.startswith("theme not loaded") for item in diagnostics)


def test_a_duplicate_theme_name_keeps_the_first_file(tmp_path: Path) -> None:
    folder = _themes_dir(tmp_path)
    write_json(folder / "a.json", {"name": "Same", "overrides": {"claude": "#111111"}})
    write_json(folder / "b.json", {"name": "same", "overrides": {"claude": "#222222"}})
    themes, diagnostics = discover_plugin_themes("p", tmp_path)
    assert [item.colors["claude"] for item in themes] == ["#111111"]
    assert "already defined by a.json" in diagnostics[0].message


def test_symlinked_theme_files_and_directories_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    write_json(outside, {"name": "Outside", "overrides": {}})
    root = tmp_path / "plugin"
    folder = _themes_dir(root)
    (folder / "link.json").symlink_to(outside)
    assert discover_plugin_themes("p", root) == ((), ())
    elsewhere = tmp_path / "elsewhere"
    write_json(elsewhere / "x.json", {"name": "X", "overrides": {}})
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "themes").symlink_to(elsewhere, target_is_directory=True)
    assert discover_plugin_themes("p", linked) == ((), ())


def test_a_plugin_without_themes_has_none(tmp_path: Path) -> None:
    assert discover_plugin_themes("p", plugin_tree(tmp_path / "p", "p")) == ((), ())


def _themes(*names: str) -> tuple[PluginTheme, ...]:
    return tuple(PluginTheme(plugin, name, Path(f"{name}.json"), "claude", "dark", {}) for plugin, name in (item.split(":") for item in names))


def test_find_theme_takes_qualified_or_bare_names_case_insensitively() -> None:
    themes = _themes("dracula:Dracula", "nord:Nord")
    assert find_theme(themes, "dracula:dracula").qualified_name == "dracula:Dracula"
    assert find_theme(themes, " NORD ").qualified_name == "nord:Nord"


def test_find_theme_rejects_unknown_and_ambiguous_names() -> None:
    themes = _themes("a:Dusk", "b:Dusk")
    with pytest.raises(ValueError, match="no theme named 'Dawn'"):
        find_theme(themes, "Dawn")
    with pytest.raises(ValueError, match="ambiguous.*a:Dusk, b:Dusk"):
        find_theme(themes, "dusk")
    assert find_theme(themes, "b:dusk").plugin == "b"


def test_installed_plugin_themes_are_namespaced_and_listed_in_details(tmp_path: Path, workspace: Path) -> None:
    source = tmp_path / "dracula"
    shutil.copytree(DRACULA, source)
    install_plugin(str(source), cwd=tmp_path)
    found = resolve_plugins(workspace)
    assert [item.qualified_name for item in found.themes] == ["dracula:Dracula", "dracula:Dracula (ANSI)"]
    assert found.diagnostics == ()
    assert "    themes: dracula:Dracula, dracula:Dracula (ANSI)" in plugin_details(found.find("dracula"))


def test_a_disabled_plugin_offers_no_themes(tmp_path: Path, workspace: Path) -> None:
    source = tmp_path / "dracula"
    shutil.copytree(DRACULA, source)
    install_plugin(str(source), cwd=tmp_path)
    set_enabled("dracula", False, workspace)
    assert resolve_plugins(workspace).themes == ()


def test_a_bad_theme_file_is_a_diagnostic_of_resolve_not_a_failed_plugin(workspace: Path) -> None:
    root = plugin_tree(workspace / ".symphony" / "plugins" / "p", "p")
    (_themes_dir(root) / "broken.json").write_text("{", encoding="utf-8")
    found = resolve_plugins(workspace)
    assert [item.name for item in found.plugins] == ["p"]
    assert [item.level for item in found.diagnostics] == ["error"]
