"""Read-only tools batch; the child model never outranks the cheap sibling."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tools import BashTool, MemoryGetTool, MemorySearchTool, MemoryTool


def test_read_only_memory_tools_are_parallel_and_writes_stay_serial(tmp_path: Path) -> None:
    assert MemorySearchTool(tmp_path).parallel is True
    assert MemoryGetTool(tmp_path).parallel is True
    assert MemoryTool(tmp_path).parallel is False
    assert BashTool(str(tmp_path)).parallel is False


def test_child_model_stays_at_or_below_the_cheap_sibling() -> None:
    from coding_agent.agent import _bounded_child_model, child_model_id

    cheap = child_model_id("openai:gpt-5.6-luna")
    assert cheap is not None and "mini" in cheap
    assert _bounded_child_model("openai:gpt-5.6-luna", "") == cheap
    assert _bounded_child_model("openai:gpt-5.6-luna", "openai:gpt-5.6-luna") == cheap
    assert _bounded_child_model("openai:gpt-5.6-luna", "openai:gpt-5.6-sol") == cheap
    assert _bounded_child_model("openai:gpt-5.4-mini", "") is None
    assert _bounded_child_model("ollama:qwen", "ollama:qwen") is None


def test_bash_description_steers_toward_pipelines_and_scripts() -> None:
    description = BashTool.description
    assert "chain with &&" in description and "a pipe to filter" in description
    assert "exit=N" in description
