"""Harness-validated patch tests (whitespace-preserving)."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from coding_agent.tools import PatchArgs, PatchTool


async def _invoke(tool, **kwargs):
    return await tool.execute(control_plane=None, args=kwargs)


def test_patch_args_preserve_whitespace() -> None:
    args = PatchArgs.model_validate(
        {
            "path": "  app.py  ",
            "old_str": "    return x\n",
            "new_str": "    return y\n",
        }
    )
    assert args.path == "app.py"
    assert args.old_str == "    return x\n"
    assert args.new_str == "    return y\n"


def test_patch_via_harness_preserves_indentation_and_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    original = "def f():\n    if True:\n        return 1\n\n"
    target.write_text(original, encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()

    result = asyncio.run(
        _invoke(
            tool,
            path="app.py",
            old_str="        return 1\n",
            new_str="        return 2\n",
        )
    )
    assert result.startswith("patched app.py")
    updated = target.read_text(encoding="utf-8")
    assert updated == "def f():\n    if True:\n        return 2\n\n"
    assert updated.endswith("\n")


def test_patch_via_harness_blank_lines_and_deletion(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("a\n\n\nb\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()

    result = asyncio.run(
        _invoke(
            tool,
            path="notes.txt",
            old_str="\n\nb\n",
            new_str="",
        )
    )
    assert result.startswith("patched notes.txt")
    assert target.read_text(encoding="utf-8") == "a\n"


def test_patch_duplicate_matches_require_replace_all(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\nx\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()

    err = asyncio.run(_invoke(tool, path="a.txt", old_str="x", new_str="y"))
    assert err.startswith("error:")
    assert "2 times" in err

    ok = asyncio.run(
        _invoke(tool, path="a.txt", old_str="x", new_str="y", replace_all=True)
    )
    assert ok.startswith("patched a.txt (2 replacement")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "y\ny\n"


def test_patch_utf8_content(tmp_path: Path) -> None:
    (tmp_path / "u.txt").write_text("café\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()
    result = asyncio.run(_invoke(tool, path="u.txt", old_str="café", new_str="☕"))
    assert result.startswith("patched u.txt")
    assert (tmp_path / "u.txt").read_text(encoding="utf-8") == "☕\n"


def test_patch_path_escape_rejected(tmp_path: Path) -> None:
    tool = PatchTool(tmp_path).as_harness_tool()
    result = asyncio.run(
        _invoke(tool, path="../outside.txt", old_str="a", new_str="b")
    )
    assert "escapes workspace" in result


def test_patch_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    victim = outside / "secret.txt"
    victim.write_text("secret\n", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    link = workspace / "link.txt"
    link.symlink_to(victim)

    tool = PatchTool(workspace).as_harness_tool()
    # resolve() follows the symlink; path must be rejected as escaping.
    result = asyncio.run(_invoke(tool, path="link.txt", old_str="secret", new_str="x"))
    assert "escapes workspace" in result or "error:" in result
    assert victim.read_text(encoding="utf-8") == "secret\n"


def test_patch_write_failure(tmp_path: Path) -> None:
    target = tmp_path / "ro.txt"
    target.write_text("hello\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()

    os.chmod(target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        result = asyncio.run(_invoke(tool, path="ro.txt", old_str="hello", new_str="bye"))
        assert result.startswith("error: failed to write")
    finally:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
