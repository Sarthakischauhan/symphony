"""Unit tests for workspace tools (no live API)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tools import (
    BashTool,
    GrepTool,
    ReadFileTool,
    WriteFileTool,
    build_tools,
)


def test_build_tools_registers_expected_names(tmp_path: Path) -> None:
    tools = build_tools(tmp_path)
    assert [tool.name for tool in tools] == [
        "read_file",
        "write_file",
        "bash",
        "grep",
    ]


def test_write_and_read_file_roundtrip(tmp_path: Path) -> None:
    write = WriteFileTool(tmp_path)
    read = ReadFileTool(tmp_path)

    assert write.run("notes/hello.txt", "hello world") == "wrote notes/hello.txt (11 bytes)"
    assert read.run("notes/hello.txt") == "hello world"


def test_read_file_missing(tmp_path: Path) -> None:
    read = ReadFileTool(tmp_path)
    assert read.run("missing.txt") == "error: file not found: missing.txt"


def test_path_escape_rejected(tmp_path: Path) -> None:
    read = ReadFileTool(tmp_path)
    with pytest.raises(ValueError, match="escapes workspace"):
        read.resolve_path("../outside.txt")


def test_bash_runs_in_workspace(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("ok", encoding="utf-8")
    bash = BashTool(tmp_path)
    assert bash.run("cat marker.txt") == "ok"
    assert "exit=1" in bash.run("false")


def test_grep_finds_matches_with_glob(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("alpha in text\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("alpha = 2\n", encoding="utf-8")

    grep = GrepTool(tmp_path)
    result = grep.run(pattern="alpha", glob="*.py")

    assert "a.py:1:def alpha():" in result
    assert "nested/c.py:1:alpha = 2" in result
    assert "b.txt" not in result


def test_grep_no_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    grep = GrepTool(tmp_path)
    assert "no matches" in grep.run(pattern="zzzz")


def test_grep_invalid_regex(tmp_path: Path) -> None:
    grep = GrepTool(tmp_path)
    assert grep.run(pattern="[unterminated").startswith("error: invalid regex")


def test_harness_tool_schema_excludes_self(tmp_path: Path) -> None:
    tool = ReadFileTool(tmp_path).as_harness_tool()
    schema = tool.get_schema()
    assert schema["name"] == "read_file"
    assert "path" in schema["parameters"]["properties"]
    assert "path" in schema["parameters"]["required"]
