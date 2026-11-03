"""Marketplace files in three formats, and every way a plugin's source can be written."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.addons.plugins.marketplace import plugin_origin, read_marketplace
from coding_agent.extensions.source import GITHUB_BASE, Source
from extension_fixtures import PSTACK, write_json


@pytest.mark.parametrize("path", [".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json"])
def test_each_marketplace_file_location_is_read(tmp_path: Path, path: str) -> None:
    write_json(tmp_path / path, {"name": "m", "plugins": [{"name": "p", "source": "./p"}]})
    assert read_marketplace(tmp_path).entry("p").source == "./p"


def test_first_valid_file_wins_and_a_missing_one_is_explained(tmp_path: Path) -> None:
    (tmp_path / ".agents" / "plugins").mkdir(parents=True)
    (tmp_path / ".agents" / "plugins" / "marketplace.json").write_text("[]")
    write_json(tmp_path / ".claude-plugin" / "marketplace.json", {"name": "claude", "plugins": []})
    assert read_marketplace(tmp_path).name == "claude"
    with pytest.raises(ValueError, match="no marketplace file"):
        read_marketplace(tmp_path / "nowhere")


def test_unknown_plugin_lists_what_the_marketplace_has(tmp_path: Path) -> None:
    write_json(tmp_path / ".claude-plugin" / "marketplace.json", {"name": "m", "plugins": [{"name": "p", "source": "./p"}]})
    with pytest.raises(ValueError, match="lists: p"):
        read_marketplace(tmp_path).entry("other")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("./plugins/x", Source("local", "/root", subdir="./plugins/x")),
        ({"source": "local", "path": "./plugins/x"}, Source("local", "/root", subdir="./plugins/x")),
        ({"source": "github", "repo": "o/r", "ref": "v1"}, Source("git", f"{GITHUB_BASE}o/r.git", "v1")),
        ({"source": "url", "url": "https://h/r.git"}, Source("git", "https://h/r.git")),
        ({"source": "git-subdir", "url": "https://h/r.git", "path": "pkg", "ref": "main"}, Source("git", "https://h/r.git", "main", "pkg")),
    ],
)
def test_source_forms(tmp_path: Path, source: object, expected: Source) -> None:
    write_json(tmp_path / ".claude-plugin" / "marketplace.json", {"name": "m", "plugins": [{"name": "p", "source": source}]})
    origin = plugin_origin(read_marketplace(tmp_path).entry("p"), Path("/root"))
    assert origin.source == expected


def test_a_sha_pin_travels_with_the_origin(tmp_path: Path) -> None:
    write_json(tmp_path / ".claude-plugin" / "marketplace.json", {"name": "m", "plugins": [{"name": "p", "source": {"source": "github", "repo": "o/r", "sha": "abc123"}}]})
    assert plugin_origin(read_marketplace(tmp_path).entry("p"), tmp_path).sha == "abc123"


@pytest.mark.parametrize("source", ["../out", "/abs", "", {"source": "local", "path": "../x"}, {"source": "url"}])
def test_sources_that_escape_or_lack_a_location_are_refused(tmp_path: Path, source: object) -> None:
    write_json(tmp_path / ".claude-plugin" / "marketplace.json", {"name": "m", "plugins": [{"name": "p", "source": source}]})
    with pytest.raises(ValueError):
        plugin_origin(read_marketplace(tmp_path).entry("p"), tmp_path)


def test_the_real_pstack_claude_marketplace_files_both_parse() -> None:
    root = PSTACK / "pstack-claude"
    assert read_marketplace(root).name == "pstack-claude"  # .agents/plugins is first (Codex order)
    assert plugin_origin(read_marketplace(root).entry("pstack"), root).source.subdir == "./plugins/pstack"
