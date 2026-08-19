"""Tests for the intentionally small coding-agent tool surface."""

from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path

from coding_agent.tools import (
    BashTool,
    PatchTool,
    SearchTool,
    WriteFileArgs,
    WriteFileTool,
    build_tools,
    wrap_with_approvals,
)
from coding_agent.tools.approvals import approval_prompt
from coding_agent.tools.bash import MAX_OUTPUT_BYTES
from core_harness import NullControlPlane


def test_tool_surface_is_small(tmp_path: Path) -> None:
    assert [tool.name for tool in build_tools(tmp_path)] == [
        "read_file", "write_file", "patch", "bash", "search", "ask_user"
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


def test_bash_is_async_and_does_not_use_blocking_run() -> None:
    source = inspect.getsource(BashTool)
    assert "subprocess.run" not in source
    assert inspect.iscoroutinefunction(BashTool.run)


def test_bash_caps_and_times_out_without_blocking(tmp_path: Path) -> None:
    tool = BashTool(tmp_path).as_harness_tool()

    async def _run() -> None:
        capped = await tool.execute(
            control_plane=None,
            args={"command": "python3 -c \"print('x' * 80_000)\""},
        )
        assert "truncated" in capped
        assert len(capped.encode("utf-8")) < MAX_OUTPUT_BYTES + 200

        started = time.monotonic()
        timed_out = await tool.execute(
            control_plane=None,
            args={"command": "sleep 30", "timeout": 1},
        )
        assert "timed out" in timed_out
        assert time.monotonic() - started < 5

    asyncio.run(_run())


def test_bash_cancel_kills_process_group(tmp_path: Path) -> None:
    tool = BashTool(tmp_path).as_harness_tool()

    async def _run() -> None:
        task = asyncio.create_task(
            tool.execute(
                control_plane=None,
                args={"command": "sleep 30", "timeout": 30},
            )
        )
        await asyncio.sleep(0.15)
        task.cancel()
        started = time.monotonic()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert time.monotonic() - started < 2

    asyncio.run(_run())


def test_approvals_allow_once_and_deny(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    needed, prompt = approval_prompt("bash", {"command": "ls"}, tmp_path)
    assert needed
    assert "ls" in prompt
    overwrite, overwrite_prompt = approval_prompt(
        "write_file", {"path": "existing.txt"}, tmp_path
    )
    assert overwrite
    assert "Overwrite" in overwrite_prompt
    broad, _ = approval_prompt(
        "patch",
        {"path": "existing.txt", "old_str": "x" * 500, "new_str": "y", "replace_all": False},
        tmp_path,
    )
    assert broad
    surgical, _ = approval_prompt(
        "patch",
        {"path": "existing.txt", "old_str": "old", "new_str": "new", "replace_all": False},
        tmp_path,
    )
    assert not surgical

    class AskingPlane(NullControlPlane):
        def __init__(self, answer: str) -> None:
            super().__init__()
            self.answer = answer

        async def ask_user(self, request_id: str) -> str:
            del request_id
            return self.answer

    wrapped = wrap_with_approvals([BashTool(tmp_path).as_harness_tool()], tmp_path)

    async def _run() -> None:
        denied = await wrapped[0].execute(
            control_plane=AskingPlane("Deny"),
            args={"command": "echo hi"},
        )
        allowed = await wrapped[0].execute(
            control_plane=AskingPlane("Allow once"),
            args={"command": "echo hi"},
        )
        skipped = await wrapped[0].execute(
            control_plane=NullControlPlane(),
            args={"command": "echo hi"},
        )
        assert denied.startswith("error: tool call denied")
        assert "hi" in allowed
        assert "hi" in skipped

    asyncio.run(_run())
