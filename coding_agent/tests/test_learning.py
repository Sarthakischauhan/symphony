"""Tests for .symphony self-learning loop."""

from __future__ import annotations

from pathlib import Path

from core_ai.types import Message
from core_harness import HarnessResult
from core_harness.models.harness import UsageTotals

from coding_agent.learning import LearningLoop, LearningStore


def _result_with_tools(*tool_payloads: tuple[str, str, str]) -> HarnessResult:
    """Build a harness result from (tool_id, tool_name, content) triples."""
    messages: list[Message] = [
        Message(role="system", content="sys"),
        Message(role="user", content="do the thing"),
    ]
    tool_calls = []
    for tool_id, name, _content in tool_payloads:
        tool_calls.append({"id": tool_id, "name": name, "arguments": {}})
    if tool_calls:
        messages.append(Message(role="assistant", content="", tool_calls=tool_calls))
    for tool_id, _name, content in tool_payloads:
        messages.append(Message(role="tool", content=content, tool_call_id=tool_id))
    messages.append(Message(role="assistant", content="done"))
    return HarnessResult(
        output_text="done",
        messages=messages,
        usage=UsageTotals(total_tokens=10),
    )


def test_learning_loop_records_worked_and_failed(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    loop = LearningLoop(store)

    result = _result_with_tools(
        ("1", "patch", "patched app.py (1 replacement(s), +4 bytes)"),
        ("2", "bash", "exit=1\nboom"),
    )
    lesson = loop.after_task("Fix greeting", result)

    assert lesson.outcome == "mixed"
    assert any("patch succeeded" in tip for tip in lesson.worked)
    assert any("bash failed" in tip for tip in lesson.failed)
    assert store.lessons_path.exists()
    assert store.playbook_path.exists()

    playbook = store.playbook_path.read_text(encoding="utf-8")
    assert "## What worked" in playbook
    assert "## What did not work" in playbook
    assert "patch succeeded" in playbook
    assert "bash failed" in playbook


def test_learning_playbook_injected_into_context(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    loop = LearningLoop(store)
    loop.after_task(
        "Write hello",
        _result_with_tools(("1", "write_file", "wrote hello.txt (5 bytes)")),
    )

    context = store.playbook_context()
    assert "Lessons from prior tasks" in context
    assert "write_file succeeded" in context


def test_failed_only_outcome(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    loop = LearningLoop(store)
    lesson = loop.after_task(
        "Broken patch",
        _result_with_tools(("1", "patch", "error: old_str not found in file")),
    )
    assert lesson.outcome == "failed"
