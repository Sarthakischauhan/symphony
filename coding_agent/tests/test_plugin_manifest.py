"""Plugin manifests in every format, and what is reported as unsupported."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.addons.plugins import read_manifest
from extension_fixtures import PSTACK, write_json


def test_formats_are_tried_in_codex_order(tmp_path: Path) -> None:
    for relative, name in (
        (".cursor-plugin/plugin.json", "cursor"), (".claude-plugin/plugin.json", "claude"),
        (".codex-plugin/plugin.json", "codex"), ("plugin.json", "root"),
    ):
        write_json(tmp_path / relative, {"name": name})
        assert read_manifest(tmp_path).manifest.name == name


def test_a_broken_first_manifest_falls_through_to_the_next_valid_one(tmp_path: Path) -> None:
    (tmp_path / "plugin.json").write_text("{not json")
    write_json(tmp_path / ".claude-plugin" / "plugin.json", {"name": "ok"})
    assert read_manifest(tmp_path).manifest.name == "ok"


def test_errors_name_the_file_and_the_field(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"name": "bad name!", "skills": ["../out"]})
    with pytest.raises(ValueError) as caught:
        read_manifest(tmp_path)
    assert "plugin.json: name" in str(caught.value)
    with pytest.raises(ValueError, match="no plugin manifest"):
        read_manifest(tmp_path / "missing")


def test_the_old_symphony_format_is_not_a_manifest(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"schema_version": 1, "id": "demo", "skills": ["skills"]})
    with pytest.raises(ValueError, match="name"):
        read_manifest(tmp_path)


def test_defaults_and_shapes(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"name": "a", "description": "Two\n  lines"})
    manifest = read_manifest(tmp_path).manifest
    assert manifest.skills == ("./skills/",) and manifest.description == "Two lines" and manifest.symphony is None
    write_json(tmp_path / "plugin.json", {"name": "a", "skills": "./s/"})
    assert read_manifest(tmp_path).manifest.skills == ("./s/",)
    write_json(tmp_path / "plugin.json", {"name": "a", "skills": ["./x/", "./y/"]})
    assert read_manifest(tmp_path).manifest.skills == ("./x/", "./y/")


def test_symphony_addon_is_declared_under_extensions(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"name": "a", "extensions": {"symphony": {"addons": "code"}}})
    with pytest.raises(ValueError, match="not a directory"):
        read_manifest(tmp_path)
    (tmp_path / "code").mkdir()
    loaded = read_manifest(tmp_path)
    assert loaded.manifest.symphony is not None and loaded.manifest.symphony.addons == "code"
    write_json(tmp_path / "plugin.json", {"name": "a", "extensions": {"symphony": {"addons": "../x"}}})
    with pytest.raises(ValueError, match="relative"):
        read_manifest(tmp_path)


def test_unsupported_contributions_come_from_manifest_keys_and_tree_markers(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"name": "a", "hooks": "./hooks.json", "mcpServers": {}})
    (tmp_path / "agents").mkdir()
    (tmp_path / "automations").mkdir()
    labels = [label for label, _ in read_manifest(tmp_path).skipped]
    assert labels == ["agents", "hooks", "automations", "mcpServers"]
    assert all(reason for _, reason in read_manifest(tmp_path).skipped)


def test_a_plain_plugin_skips_nothing(tmp_path: Path) -> None:
    write_json(tmp_path / "plugin.json", {"name": "plain"})
    assert read_manifest(tmp_path).skipped == ()


def test_the_cursor_format_pstack_fixture_reads_with_agents_and_automations_skipped() -> None:
    loaded = read_manifest(PSTACK / "pstack")
    assert (loaded.manifest.name, loaded.manifest.version) == ("pstack", "0.15.36")
    assert loaded.path.name == "plugin.json" and loaded.path.parent == PSTACK / "pstack"
    assert [label for label, _ in loaded.skipped] == ["agents", "automations"]


def test_the_claude_format_pstack_fixture_prefers_codex_manifest_and_skips_hooks_and_agents() -> None:
    loaded = read_manifest(PSTACK / "pstack-claude" / "plugins" / "pstack")
    assert loaded.path.parent.name == ".codex-plugin" and loaded.manifest.version == "0.9.114"
    assert [label for label, _ in loaded.skipped] == ["agents", "hooks"]
