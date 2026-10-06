"""Resume keeps asynchronous work in cards rather than synthetic user prompts."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core_ai.types import Message
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.runtime.subagent import SubagentWidget
from coding_agent.tui.screens.history import _history_widgets, load_session_history
from coding_agent.tui.tools import BashToolWidget, CompletedRunSummary
from coding_agent.tui.transcript import AssistantMessage, UserMessage


def _fixture():
    calls = [
        {
            "id": "spawn",
            "function": {"name": "spawn_agent", "arguments": json.dumps({"prompt": "Inspect", "label": "Inspector"})},
        },
        {
            "id": "bash",
            "function": {"name": "bash", "arguments": json.dumps({"command": "pytest", "background": True})},
        },
    ]
    messages = [
        Message(role="user", content="Parent task"),
        Message(role="assistant", content="Starting work", tool_calls=calls),
        Message(role="tool", tool_call_id="spawn", content='{"child_id":"child"}'),
        Message(
            role="tool",
            tool_call_id="bash",
            content="started background job abc123\nlog: /tmp/abc123.log\nWait for completion",
        ),
        Message(role="user", content="Subagent Inspector (child) completed.\nChild-only output"),
        Message(
            role="user",
            content="Background job abc123 exit=0 after 1.0s. Last output:\nJob-only output\nFull log: /tmp/abc123.log",
        ),
        Message(role="assistant", content="Parent answer"),
    ]
    metadata = {
        "child_id": "child",
        "agent_id": "parent",
        "tool_call_id": "spawn",
        "child_session_id": "child-session",
        "label": "Inspector",
        "prompt": "Inspect",
        "status": "completed",
        "output_text": "Child-only output",
    }
    events = [
        ("agent_spawned", metadata),
        ("reasoning_completed", {"agent_id": "child", "parent_id": "parent", "text": "Child-only thought"}),
        (
            "tool_execution_completed",
            {
                "agent_id": "child",
                "parent_id": "parent",
                "tool_call_id": "child-tool",
                "tool_name": "read_file",
                "arguments": {"path": "child.py"},
            },
        ),
        ("tool_execution_completed", {"tool_call_id": "spawn", "collected": True}),
    ]
    return messages, events, metadata


@pytest.mark.parametrize("collected", [False, True])
def test_history_async_results_stay_in_cards(collected):
    messages, events, _ = _fixture()
    if not collected:
        events = [(kind, payload) for kind, payload in events if not payload.get("collected")]
    widgets = _history_widgets(messages, events)
    assert [widget.message_text for widget in widgets if isinstance(widget, UserMessage)] == ["Parent task"]
    assert [widget.message_text for widget in widgets if isinstance(widget, AssistantMessage)] == (
        ["Parent answer"] if collected else ["Starting work", "Parent answer"]
    )
    assert len([widget for widget in widgets if isinstance(widget, SubagentWidget)]) == 1
    bash = next(widget for widget in widgets if isinstance(widget, BashToolWidget))
    assert bash.call_id == "bash"
    assert "Job-only output" in bash.result
    assert not any(isinstance(widget, CompletedRunSummary) and "child-tool" in widget.call_ids for widget in widgets)


def test_completed_foreground_cards_fold_but_open_work_stays_open():
    messages = [
        Message(role="user", content="Finished task"),
        Message(role="assistant", content="", tool_calls=[
            {"id": "bash", "function": {"name": "bash", "arguments": json.dumps({"command": "pytest"})}},
            {"id": "spawn", "function": {"name": "spawn_agent", "arguments": json.dumps({"prompt": "Inspect"})}},
        ]),
        Message(role="tool", tool_call_id="bash", content="2 passed"),
        Message(role="tool", tool_call_id="spawn", content='{"child_id":"child"}'),
        Message(role="assistant", content="Finished answer"),
        Message(role="user", content="Current task"),
        Message(role="assistant", content="", tool_calls=[
            {"id": "bash-live", "function": {"name": "bash", "arguments": json.dumps({"command": "sleep 5"})}},
            {"id": "spawn-live", "function": {"name": "spawn_agent", "arguments": json.dumps({"prompt": "Continue"})}},
        ]),
        Message(role="tool", tool_call_id="bash-live", content=""),
        Message(role="tool", tool_call_id="spawn-live", content='{"child_id":"child-live"}'),
    ]
    events = [
        ("tool_execution_completed", {"run_id": "old", "tool_call_id": "bash", "collected": True}),
        ("agent_spawned", {"run_id": "old", "tool_call_id": "spawn", "child_id": "child", "collected": True}),
        ("tool_execution_completed", {"run_id": "new", "tool_call_id": "bash-live"}),
        ("agent_spawned", {"run_id": "new", "tool_call_id": "spawn-live", "child_id": "child-live"}),
    ]
    widgets = _history_widgets(messages, events)
    assert [widget.call_id for widget in widgets if isinstance(widget, SubagentWidget)] == ["spawn", "spawn-live"]
    assert not [widget for widget in widgets if isinstance(widget, BashToolWidget) and widget.call_id == "bash"]
    summary = next(widget for widget in widgets if isinstance(widget, CompletedRunSummary))
    assert "bash" in summary.call_ids
    assert [widget.call_id for widget in widgets if isinstance(widget, BashToolWidget)] == ["bash-live"]


def test_history_recognizes_legacy_child_result_without_events():
    messages, _, _ = _fixture()
    widgets = _history_widgets(messages, [])
    assert [widget.message_text for widget in widgets if isinstance(widget, UserMessage)] == ["Parent task"]


def test_history_preserves_real_user_messages_mentioning_jobs():
    messages = [
        Message(role="user", content="Background job unknown exit=0 after 1.0s. Last output:\ntext\nFull log: /tmp/log")
    ]
    widgets = _history_widgets(messages, [])
    assert len(widgets) == 1 and isinstance(widgets[0], UserMessage)


def test_resumed_child_card_opens_child_transcript(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    messages, events, metadata = _fixture()

    class Persistence:
        async def load_conversation(self, **kwargs):
            return messages

        async def load_events(self, *, session_id):
            if session_id == "child-session":
                return [("run_completed", {"output_text": "Child-only output"})]
            return events

        async def load_children(self, **kwargs):
            return [metadata]

    app = CodingAgentApp(workspace=tmp_path)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            app._agent = SimpleNamespace(
                persistence=Persistence(),
                session_id="parent-session",
                harness=SimpleNamespace(model_id="fake", state=SimpleNamespace(context_limit=lambda _: 10000)),
            )
            await load_session_history(app._agent, app)
            await app.restore_subagents()
            await pilot.pause()
            card = app.query_one(SubagentWidget)
            assert card is app._tools["spawn"]
            assert card.record is app._subagents["child"]
            assert [widget.message_text for widget in app.query(UserMessage)] == ["Parent task"]
            assert card.open_screen()
            await pilot.pause()
            assert app.screen.child_id == "child"
            app.pop_screen()
            app._agent = None

    asyncio.run(run())


def test_live_background_card_survives_completion(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            app.set_thinking("Working")
            app.add_tool("bash", "bash")
            app.update_tool("bash", arguments={"command": "pytest", "background": True}, status="running")
            app.update_tool("bash", status="done", result="started background job abc123")
            await pilot.pause()
            card = app.query_one(BashToolWidget)
            app.finish_process("Done")
            await pilot.pause()
            assert app.query_one(BashToolWidget) is card

    asyncio.run(run())
