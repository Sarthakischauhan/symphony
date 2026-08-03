"""Unit tests for the patch (edit-file) tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tools import PatchTool


def test_patch_replaces_unique_match(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def greet(name):\n    return name\n", encoding="utf-8")

    patch = PatchTool(tmp_path)
    result = patch.run(
        path="app.py",
        old_str="return name",
        new_str='return f"hi {name}"',
    )
    assert result.startswith("patched app.py")
    assert 'return f"hi {name}"' in target.read_text(encoding="utf-8")


def test_patch_requires_unique_match_unless_replace_all(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\nx\n", encoding="utf-8")
    patch = PatchTool(tmp_path)

    err = patch.run(path="a.txt", old_str="x", new_str="y")
    assert err.startswith("error:")
    assert "2 times" in err

    ok = patch.run(path="a.txt", old_str="x", new_str="y", replace_all=True)
    assert ok.startswith("patched a.txt (2 replacement")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "y\ny\n"


def test_patch_missing_old_str(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    patch = PatchTool(tmp_path)
    assert "not found" in patch.run(path="a.txt", old_str="missing", new_str="x")


def test_patch_missing_file(tmp_path: Path) -> None:
    patch = PatchTool(tmp_path)
    assert patch.run(path="nope.txt", old_str="a", new_str="b").startswith("error: file not found")
