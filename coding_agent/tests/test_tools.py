"""Tests for the intentionally small coding-agent tool surface."""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent.tools import PatchTool, SearchTool, WriteFileArgs, WriteFileTool, build_tools


def test_tool_surface_is_small(tmp_path: Path) -> None:
    assert [tool.name for tool in build_tools(tmp_path)] == [
        "read_file", "write_file", "patch", "bash", "search"
    ]


def test_write_file_preserves_whitespace_through_validation(tmp_path: Path) -> None:
    args = WriteFileArgs.model_validate({"path": "  a.py  ", "content": "    x = 1\n\n"})
    assert args.path == "a.py"
    assert args.content == "    x = 1\n\n"
    tool = WriteFileTool(tmp_path).as_harness_tool()
    result = asyncio.run(tool.execute(control_plane=None, args=args.model_dump()))
    assert result.startswith("wrote a.py")
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "    x = 1\n\n"


def test_search_content_literal_regex_and_glob(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("alpha text\n", encoding="utf-8")
    search = SearchTool(tmp_path)
    literal = search.run(query="alpha", glob="*.py")
    assert "a.py:1:def alpha():" in literal
    assert "b.txt" not in literal
    regex = search.run(query=r"return\s+\d", regex=True)
    assert "a.py:2:" in regex


def test_search_file_names(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    result = SearchTool(tmp_path).run(query="agent", mode="files")
    assert "agent.py" in result
    assert "notes.txt" not in result


def test_search_rejects_escape_and_bad_regex(tmp_path: Path) -> None:
    search = SearchTool(tmp_path)
    assert "escapes workspace" in search.run(query="x", path="../outside")
    assert search.run(query="[", regex=True).startswith("error: invalid regex")


def test_patch_keeps_unique_match_contract(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("x\nx\n", encoding="utf-8")
    patch = PatchTool(tmp_path)
    assert "matched 2 times" in patch.run("a.txt", "x", "y")
    assert patch.run("a.txt", "x", "y", replace_all=True).startswith("patched")
    assert path.read_text(encoding="utf-8") == "y\ny\n"
