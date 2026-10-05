"""SearchTool prefers ripgrep and falls back to the Python walker; read-only tools batch."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from coding_agent.tools import BashTool, PatchTool, ReadFileTool, SearchTool, WriteFileTool
from coding_agent.tools import search as search_module

HAS_RG = shutil.which("rg") is not None


@pytest.fixture(params=["rg", "python"])
def backend(request, monkeypatch) -> str:
    """Run a test once through ripgrep and once through the Python fallback."""
    if request.param == "rg":
        if not HAS_RG:
            pytest.skip("ripgrep is not installed")
    else:
        monkeypatch.setattr(search_module, "find_rg", lambda: None)
    return request.param


def _tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.txt").write_text("alpha text\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.py").write_text("alpha\n", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "h.py").write_text("alpha\n", encoding="utf-8")
    (root / "ignored").mkdir()
    (root / "ignored" / "x.py").write_text("alpha\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\x00alpha" + b"x" * 8)


def test_search_skips_same_paths_with_either_backend(tmp_path: Path, backend: str) -> None:
    _tree(tmp_path)  # not a git checkout: .gitignore must still apply
    search = SearchTool(tmp_path)
    content = search.run(query="alpha")
    assert content.splitlines()[1:] == ["src/a.py:1:def alpha():", "src/b.txt:1:alpha text"]
    assert search.run(query="alpha", glob="*.py").splitlines()[1:] == ["src/a.py:1:def alpha():"]
    assert "src/a.py:2:    return 1" in search.run(query=r"return\s+\d", regex=True)
    assert "src/b.txt:1:alpha text" in search.run(query="ALPHA TEXT", case_insensitive=True)
    assert search.run(query="a.py", mode="files").splitlines()[1:] == ["src/a.py"]
    assert search.run(query="nothing-here").startswith("no content matches")


def test_search_caps_results_and_line_length(tmp_path: Path, backend: str) -> None:
    (tmp_path / "many.txt").write_text("".join(f"hit {i} {'x' * 50}\n" for i in range(20)), encoding="utf-8")
    result = SearchTool(tmp_path).run(query="hit", max_results=3, max_line_chars=10)
    lines = result.splitlines()
    assert lines[0] == "3 content matches (capped)"
    assert lines[1:] == ["many.txt:1:hit 0 xxxx…", "many.txt:2:hit 1 xxxx…", "many.txt:3:hit 2 xxxx…"]


def test_search_uses_rg_when_present(tmp_path: Path, monkeypatch) -> None:
    if not HAS_RG:
        pytest.skip("ripgrep is not installed")
    _tree(tmp_path)
    commands: list[list[str]] = []
    real_popen = subprocess.Popen

    def spy(command, *args, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(search_module.subprocess, "Popen", spy)
    monkeypatch.setattr(SearchTool, "_python_search", lambda *a, **k: pytest.fail("python fallback used"))
    result = SearchTool(tmp_path).run(query="alpha")
    assert "src/a.py:1:def alpha():" in result
    assert len(commands) == 1 and commands[0][0] == shutil.which("rg")
    assert "--fixed-strings" in commands[0]


def test_search_falls_back_to_python_when_rg_missing(tmp_path: Path, monkeypatch) -> None:
    _tree(tmp_path)
    monkeypatch.setattr(search_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        search_module.subprocess, "Popen", lambda *a, **k: pytest.fail("rg must not run when missing")
    )
    result = SearchTool(tmp_path).run(query="alpha")
    assert result.splitlines()[1:] == ["src/a.py:1:def alpha():", "src/b.txt:1:alpha text"]


def test_search_falls_back_when_rg_rejects_a_python_regex(tmp_path: Path) -> None:
    if not HAS_RG:
        pytest.skip("ripgrep is not installed")
    (tmp_path / "a.py").write_text("foo_bar\nfoo_baz\n", encoding="utf-8")
    # Lookahead is valid Python re but not ripgrep's default engine.
    result = SearchTool(tmp_path).run(query=r"foo_(?=baz)", regex=True)
    assert result.splitlines()[1:] == ["a.py:2:foo_baz"]


def test_only_read_and_search_are_parallel(tmp_path: Path) -> None:
    assert ReadFileTool(tmp_path).parallel is True
    assert SearchTool(tmp_path).parallel is True
    assert WriteFileTool(tmp_path).parallel is False
    assert PatchTool(tmp_path).parallel is False
    assert BashTool(tmp_path).parallel is False


def test_parallel_tools_run_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    import threading

    seen: list[str] = []
    real_run = ReadFileTool.run

    def recording_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(threading.current_thread().name)
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(ReadFileTool, "run", recording_run)
    result = asyncio.run(ReadFileTool(tmp_path).execute(sink=None, args={"path": "a.txt"}))
    assert "hello" in str(result)
    assert seen and seen[0] != threading.main_thread().name
