"""Harness-validated patch tests (whitespace-preserving)."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from core_harness.tools import current_tool_call_id

from coding_agent.tools import PatchArgs, PatchTool
from coding_agent.tui.tools.calls import make_unified_diff


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
    assert ok.startswith("patched a.txt at lines 1, 2 (2 replacement")
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


@pytest.mark.parametrize(
    ("original", "old", "new", "expected"),
    [
        pytest.param("    return x  \n", "    return x\n", "    return y\n", "    return y\n", id="trailing-whitespace"),
        pytest.param("msg = \u201chello\u201d\n", 'msg = "hello"\n', 'msg = "bye"\n', 'msg = "bye"\n', id="curly-quotes"),
        pytest.param("\ufeffhello\n", "hello\n", "world\n", "\ufeffworld\n", id="bom-kept"),
    ],
)
def test_patch_unique_fuzzy_match_still_applies(
    tmp_path: Path, original: str, old: str, new: str, expected: str
) -> None:
    target = tmp_path / "a.py"
    target.write_text(original, encoding="utf-8")
    result = PatchTool(tmp_path).run("a.py", old, new)
    assert result.startswith("patched")
    assert target.read_text(encoding="utf-8") == expected


# Line numbers: the result, the protocol summary and the TUI diff all use file lines.


def numbered(count: int) -> str:
    return "".join(f"line {n}\n" for n in range(1, count + 1))


def run_as_call(tool: PatchTool, call_id: str, path: str, old: str, new: str, replace_all: bool = False) -> str:
    token = current_tool_call_id.set(call_id)
    try:
        return tool.run(path, old, new, replace_all)
    finally:
        current_tool_call_id.reset(token)


def patched_diff(tmp_path: Path, old: str, new: str) -> tuple[str, list[str]]:
    target = tmp_path / "a.py"
    if not target.exists():
        target.write_text(numbered(60), encoding="utf-8")
    tool = PatchTool(tmp_path)
    result = run_as_call(tool, "call-1", "a.py", old, new)
    # The start line is recorded per call, never parsed back out of the result.
    start = tool.start_lines.get("call-1")
    assert start is not None, result
    return result, make_unified_diff(old, new, start)


def test_patch_reports_the_file_line_and_offsets_hunks(tmp_path: Path) -> None:
    result, diff = patched_diff(tmp_path, "line 41\nline 42\nline 43\n", "line 41\nLINE 42\nline 43\n")
    assert result.startswith("patched a.py at line 41 (1 replacement")
    assert diff[0] == "@@ -41,3 +41,3 @@"


def test_patch_multi_hunk_headers_all_shift(tmp_path: Path) -> None:
    old = "".join(f"line {n}\n" for n in range(10, 31))
    new = old.replace("line 11\n", "LINE 11\n").replace("line 29\n", "LINE 29\n")
    _, diff = patched_diff(tmp_path, old, new)
    headers = [line for line in diff if line.startswith("@@")]
    # Two hunks, each numbered from line 10 of the file, not from 1.
    assert headers == ["@@ -10,5 +10,5 @@", "@@ -26,5 +26,5 @@"]


def test_patch_insert_at_top(tmp_path: Path) -> None:
    result, diff = patched_diff(tmp_path, "line 1\n", "# header\nline 1\n")
    assert "at line 1 " in result
    assert diff[:3] == ["@@ -1 +1,2 @@", "+# header", " line 1"]


def test_patch_delete_at_end(tmp_path: Path) -> None:
    result, diff = patched_diff(tmp_path, "line 59\nline 60\n", "")
    assert "at line 59 " in result
    assert diff == ["@@ -59,2 +58,0 @@", "-line 59", "-line 60"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == numbered(58)


def test_patch_fuzzy_match_reports_its_window_line(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text(numbered(20).replace("line 15\n", "line 15   \n"), encoding="utf-8")
    # Trailing whitespace differs, so only the folded match applies.
    result, diff = patched_diff(tmp_path, "line 14\nline 15\n", "line 14\nline fifteen\n")
    assert result.startswith("patched a.py at line 14 (1 replacement")
    assert diff[0] == "@@ -14,2 +14,2 @@"


def test_patch_records_no_start_line_for_a_failed_call(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(numbered(5), encoding="utf-8")
    tool = PatchTool(tmp_path)
    assert run_as_call(tool, "miss", "a.py", "nope\n", "x\n").startswith("old_str not found")
    assert tool.start_lines == {}


def test_folded_replace_all_skips_overlapping_windows(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("a \na \na \n", encoding="utf-8")
    tool = PatchTool(tmp_path)
    # Trailing spaces force the folded path; "a\na\n" fits at lines 1 and 2,
    # but those windows overlap, so only the first one applies.
    result = run_as_call(tool, "fold", "a.txt", "a\na\n", "b\n", replace_all=True)
    assert result.startswith("patched a.txt at line 1 (1 replacement")
    assert target.read_text(encoding="utf-8") == "b\na \n"
    assert tool.start_lines == {"fold": 1}

