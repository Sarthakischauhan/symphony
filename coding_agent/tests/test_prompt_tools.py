"""Tool descriptions and parallel execution settings."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tools import BashTool, MemoryGetTool, MemorySearchTool, MemoryTool


def test_read_only_memory_tools_are_parallel_and_writes_stay_serial(tmp_path: Path) -> None:
    assert MemorySearchTool(tmp_path).parallel is True
    assert MemoryGetTool(tmp_path).parallel is True
    assert MemoryTool(tmp_path).parallel is False
    assert BashTool(str(tmp_path)).parallel is False


def test_bash_description_steers_toward_pipelines_and_scripts() -> None:
    description = BashTool.description
    assert "chain with &&" in description and "a pipe to filter" in description
    assert "exit=N" in description
