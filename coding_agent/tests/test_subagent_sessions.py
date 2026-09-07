"""Child views share parent rendering and remain isolated during live updates."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from coding_agent.persistence import JsonlPersistence
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.runtime.control_plane import HarnessEvent
from coding_agent.tui.runtime.subagent import SubagentScreen, SubagentTasksScreen
from coding_agent.tui.tools import ToolCallSummary, ToolCallWidget
from coding_agent.tui.transcript import AssistantMessage, ReasoningWidget, UserMessage


def test_child_view_compaction_and_parent_updates_are_isolated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            app.mount_transcript(UserMessage("Parent task"))
            app.add_tool("spawn", "spawn_agent")
            app.on_harness_event(HarnessEvent("agent_spawned", {
                "child_id": "child", "agent_id": "parent", "tool_call_id": "spawn",
                "prompt": "Inspect files", "label": "Inspector", "child_session_id": "child",
            }))
            seq = 0

            def emit(name, **payload):
                nonlocal seq
                seq += 1
                app.on_harness_event(HarnessEvent(name, {
                    **payload, "agent_id": "child", "parent_id": "parent",
                    "session_id": "child", "run_id": "run", "seq": seq,
                }))

            emit("run_started", model_id="fake:child")
            emit("reasoning_delta", delta="## Inspecting files\n\nHidden thought body", summary_index=0)
            app.open_subagent(app._subagents["child"])
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SubagentScreen)
            for index in range(11):
                emit("tool_call_started", tool_call_id=str(index), tool_name="read_file")
                emit("tool_execution_started", tool_call_id=str(index), tool_name="read_file", arguments={"path": f"file{index}.py"})
                emit("tool_execution_completed", tool_call_id=str(index), tool_name="read_file", result="Hidden tool output", status="success")
            emit("text_delta", delta="Child answer")
            app.set_assistant("Parent continues while child view is open")
            await pilot.pause()
            assert len(list(screen.query(ToolCallSummary))) == 1
            assert len(list(screen.query(ToolCallWidget))) == 1
            assert [item.message_text for item in screen.query(AssistantMessage)] == ["Child answer"]
            assert app._assistant.parent is not screen.query_one("#transcript")
            emit("run_completed", output_text="Child answer")
            await pilot.pause()
            assert not list(screen.query(ToolCallWidget))
            assert not list(screen.query(ReasoningWidget))
            summaries = list(screen.query(ToolCallSummary))
            assert sum(item.count for item in summaries) == 11
            summaries[0].toggle()
            assert "Thought - Inspecting files" in summaries[0].render().plain
            assert "Hidden tool output" not in summaries[0].render().plain
            assert "Hidden thought body" not in summaries[0].render().plain
            screen.refresh_record()
            assert summaries[0].is_expanded
            await pilot.press("escape")
            await pilot.pause()
            app.finish_process("Parent completed")
            await pilot.pause()
            assert app._tools["spawn"].is_attached
            await pilot.press("ctrl+g")
            await pilot.pause()
            assert isinstance(app.screen, SubagentTasksScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, SubagentScreen)
            assert sum(item.count for item in app.screen.query(ToolCallSummary)) == 11

    asyncio.run(run())


def test_duplicate_labels_bind_by_call_id_and_reject_foreign_events(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def run() -> None:
        async with app.run_test() as pilot:
            for call_id in ("a", "b"):
                app.add_tool(call_id, "spawn_agent")
            for child, call_id in (("child-b", "b"), ("child-a", "a")):
                app.on_harness_event(HarnessEvent("agent_spawned", {
                    "child_id": child, "agent_id": "parent", "tool_call_id": call_id,
                    "prompt": "same", "label": "same",
                }))
            await pilot.pause()
            assert app._tools["a"].record.agent_id == "child-a"
            assert app._tools["b"].record.agent_id == "child-b"
            record = app._subagents["child-a"]
            event = {"agent_id": "child-a", "parent_id": "parent", "run_id": "r", "seq": 1, "delta": "once"}
            record.ingest("text_delta", event)
            record.ingest("text_delta", event)
            record.ingest("text_delta", {**event, "parent_id": "foreign", "seq": 2})
            assert record.output_text == "once"

    asyncio.run(run())


def test_child_journal_reopens_after_restart(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "sessions"

    async def run() -> None:
        store = JsonlPersistence(root)
        await store.append_event(event_type="agent_spawned", payload={
            "agent_id": "parent", "child_id": "child", "session_id": "parent-session",
            "child_session_id": "child-session", "run_id": "parent-run", "seq": 1,
            "label": "Saved child", "prompt": "Saved task",
        })
        await store.append_event(event_type="run_started", payload={
            "model_id": "fake:child", "agent_id": "child", "parent_id": "parent",
            "session_id": "child-session", "run_id": "child-run", "seq": 1,
        })
        await store.append_event(event_type="run_completed", payload={
            "output_text": "Partial answer", "agent_id": "child", "parent_id": "parent",
            "session_id": "child-session", "run_id": "child-run", "seq": 2,
        })
        app = CodingAgentApp(workspace=tmp_path)
        async with app.run_test() as pilot:
            app._agent = SimpleNamespace(persistence=JsonlPersistence(root), session_id="parent-session")
            await app.restore_subagents()
            record = app._subagents["child"]
            assert record.status == "interrupted"
            app.open_subagent(record)
            await pilot.pause()
            assert app.screen.query_one(AssistantMessage).message_text == "Partial answer"
            assert app.screen._ui_state.phase == "idle"

    asyncio.run(run())
