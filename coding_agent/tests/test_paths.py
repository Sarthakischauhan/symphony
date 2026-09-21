"""Shared project-root walk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent.paths import project_root
from coding_agent.personalities import discover_personalities_path, load_personalities


def test_project_root_finds_markers_at_different_depths(tmp_path: Path) -> None:
    pyproject = tmp_path / "pkg" / "src" / "mod"
    pyproject.mkdir(parents=True)
    (tmp_path / "pkg" / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
    assert project_root(pyproject) == (tmp_path / "pkg").resolve()
    assert project_root(tmp_path / "pkg" / "src" / "mod" / "file.py") == (tmp_path / "pkg").resolve()

    git_leaf = tmp_path / "repo" / "src" / "app"
    git_leaf.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    assert project_root(git_leaf) == (tmp_path / "repo").resolve()

    catalog_leaf = tmp_path / "voice" / "inner"
    catalog_leaf.mkdir(parents=True)
    (tmp_path / "voice" / "personalities.json").write_text("{}\n", encoding="utf-8")
    assert project_root(catalog_leaf) == (tmp_path / "voice").resolve()


def test_project_root_marker_order_prefers_closer_pyproject(tmp_path: Path) -> None:
    inner = tmp_path / "outer" / "inner"
    inner.mkdir(parents=True)
    (tmp_path / "outer" / ".git").mkdir()
    (inner / "pyproject.toml").write_text("[project]\nname='inner'\n", encoding="utf-8")
    assert project_root(inner) == inner.resolve()


def test_project_root_none_without_markers(tmp_path: Path) -> None:
    leaf = tmp_path / "empty" / "nested"
    leaf.mkdir(parents=True)
    assert project_root(leaf) is None
    assert project_root(leaf / "missing.py") is None


def test_discover_personalities_path_uses_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert discover_personalities_path() is None
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    assert discover_personalities_path() is None
    catalog = tmp_path / "personalities.json"
    catalog.write_text(json.dumps({"personalities": []}), encoding="utf-8")
    assert discover_personalities_path() == catalog.resolve()
    assert load_personalities() == ()
