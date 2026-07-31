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


def test_harness_tool_schemas_include_field_descriptions(tmp_path: Path) -> None:
    tools = {tool.name: tool for tool in build_tools(tmp_path)}

    read_schema = tools["read_file"].get_schema()
    assert read_schema["name"] == "read_file"
    assert "UTF-8" in read_schema["description"]
    assert read_schema["parameters"]["type"] == "object"
    assert read_schema["parameters"]["additionalProperties"] is False
    assert read_schema["parameters"]["required"] == ["path"]
    assert "Workspace-relative path" in read_schema["parameters"]["properties"]["path"]["description"]

    write_schema = tools["write_file"].get_schema()
    assert set(write_schema["parameters"]["required"]) == {"path", "content"}
    assert "UTF-8 text content" in write_schema["parameters"]["properties"]["content"]["description"]

    bash_schema = tools["bash"].get_schema()
    assert bash_schema["parameters"]["required"] == ["command"]
    assert "Shell command" in bash_schema["parameters"]["properties"]["command"]["description"]

    grep_schema = tools["grep"].get_schema()
    grep_props = grep_schema["parameters"]["properties"]
    assert grep_schema["parameters"]["required"] == ["pattern"]
    assert "Regular expression" in grep_props["pattern"]["description"]
    assert grep_props["max_matches"]["minimum"] == 1
    assert grep_props["max_matches"]["maximum"] == 500


def test_tool_argument_validation_rejects_bad_types(tmp_path: Path) -> None:
    read = ReadFileTool(tmp_path).as_harness_tool()
    write = WriteFileTool(tmp_path).as_harness_tool()
    bash = BashTool(tmp_path).as_harness_tool()
    grep = GrepTool(tmp_path).as_harness_tool()

    async def _call(tool, **kwargs):
        return await tool.execute(control_plane=None, args=kwargs)

    import asyncio

    with pytest.raises(ValueError, match="invalid read_file arguments"):
        asyncio.run(_call(read, path=123))
    with pytest.raises(ValueError, match="invalid write_file arguments"):
        asyncio.run(_call(write, path="a.txt"))  # missing content
    with pytest.raises(ValueError, match="invalid bash arguments"):
        asyncio.run(_call(bash, command=""))
    with pytest.raises(ValueError, match="invalid grep arguments"):
        asyncio.run(_call(grep, pattern="x", max_matches=0))
