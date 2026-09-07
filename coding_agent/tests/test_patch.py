"""Harness-validated patch tests (whitespace-preserving)."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from coding_agent.tools import PatchArgs, PatchTool


async def invoke(tool, **kwargs):
    return await tool.execute(sink=None, args=kwargs)


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
        invoke(
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
        invoke(
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

    err = asyncio.run(invoke(tool, path="a.txt", old_str="x", new_str="y"))
    assert not err.startswith("error:")
    assert "2 times" in err
    assert "line 1" in err and "line 2" in err
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x\nx\n"

    ok = asyncio.run(
        invoke(tool, path="a.txt", old_str="x", new_str="y", replace_all=True)
    )
    assert ok.startswith("patched a.txt (2 replacement")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "y\ny\n"


def test_patch_utf8_content(tmp_path: Path) -> None:
    (tmp_path / "u.txt").write_text("café\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()
    result = asyncio.run(invoke(tool, path="u.txt", old_str="café", new_str="☕"))
    assert result.startswith("patched u.txt")
    assert (tmp_path / "u.txt").read_text(encoding="utf-8") == "☕\n"


def test_patch_outside_working_directory(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("a\n", encoding="utf-8")
    tool = PatchTool(cwd).as_harness_tool()
    result = asyncio.run(invoke(tool, path=str(outside), old_str="a", new_str="b"))
    assert result.startswith("patched")
    assert outside.read_text(encoding="utf-8") == "b\n"


def test_patch_follows_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    victim = outside / "secret.txt"
    victim.write_text("secret\n", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    link = workspace / "link.txt"
    link.symlink_to(victim)

    tool = PatchTool(workspace).as_harness_tool()
    result = asyncio.run(invoke(tool, path="link.txt", old_str="secret", new_str="x"))
    assert result.startswith("patched")
    assert victim.read_text(encoding="utf-8") == "x\n"


def test_patch_write_failure(tmp_path: Path) -> None:
    target = tmp_path / "ro.txt"
    target.write_text("hello\n", encoding="utf-8")
    tool = PatchTool(tmp_path).as_harness_tool()

    os.chmod(target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        result = asyncio.run(invoke(tool, path="ro.txt", old_str="hello", new_str="bye"))
        if os.geteuid() == 0:
            pytest.skip("root can write read-only files")
        assert result.startswith("error: failed to write")
    finally:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)


def test_patch_identical_strings_are_noop(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("    return x\n", encoding="utf-8")
    tool = PatchTool(tmp_path)
    result = tool.run("a.py", "    return x\n", "    return x\n")
    assert result.startswith("noop:")
    assert "error:" not in result
    assert target.read_text(encoding="utf-8") == "    return x\n"


def test_patch_miss_shows_whitespace_hint(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("    return x\n", encoding="utf-8")
    tool = PatchTool(tmp_path)
    result = tool.run("a.py", "        return x\n", "        return y\n")
    assert result.startswith("old_str not found")
    assert "error:" not in result
    assert "whitespace differs" in result
    assert "1|" in result
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "    return x\n"


def test_patch_miss_notes_already_applied(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("    return y\n", encoding="utf-8")
    result = PatchTool(tmp_path).run("a.py", "    return x\n", "    return y\n")
    assert "already contains new_str" in result
    assert "error:" not in result
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "    return y\n"


def test_patch_crlf_file_accepts_lf_needle(tmp_path: Path) -> None:
    target = tmp_path / "win.py"
    target.write_bytes(b"def f():\r\n    return 1\r\n")
    result = PatchTool(tmp_path).run("win.py", "    return 1\n", "    return 2\n")
    assert result.startswith("patched")
    assert target.read_bytes() == b"def f():\r\n    return 2\r\n"


def test_patch_unique_trailing_whitespace_still_applies(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("    return x  \n", encoding="utf-8")
    result = PatchTool(tmp_path).run("a.py", "    return x\n", "    return y\n")
    assert result.startswith("patched")
    assert target.read_text(encoding="utf-8") == "    return y\n"


def test_patch_unique_curly_quotes_still_apply(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("msg = \u201chello\u201d\n", encoding="utf-8")
    result = PatchTool(tmp_path).run("a.py", 'msg = "hello"\n', 'msg = "bye"\n')
    assert result.startswith("patched")
    assert target.read_text(encoding="utf-8") == 'msg = "bye"\n'


def test_patch_strips_bom_for_matching(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("\ufeffhello\n", encoding="utf-8")
    result = PatchTool(tmp_path).run("a.py", "hello\n", "world\n")
    assert result.startswith("patched")
    assert target.read_text(encoding="utf-8") == "\ufeffworld\n"
