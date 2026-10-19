"""Child views share parent rendering and remain isolated during live updates."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from coding_agent.addons.persistence import JsonlPersistence
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.chrome import ComposerOverlay
from coding_agent.tui.runtime.sink import HarnessEvent
from coding_agent.tui.runtime.subagent import SubagentRecord, SubagentScreen, SubagentTasksScreen
from coding_agent.tui.tools import BashToolWidget, CompletedRunSummary, ToolCallSummary, ToolCallWidget
from coding_agent.tui.transcript import AssistantMessage, UserMessage
from coding_agent.tui.transcript.messages import Notice


def test_child_tool_argument_snapshots_replace_streamed_json() -> None:
    record = SubagentRecord(agent_id="child", parent_id="parent", label="Inspector", prompt="Inspect")
    call = {"tool_call_id": "read-1", "tool_name": "read_file"}
    record.ingest("tool_call_started", call)
    record.ingest("tool_call_delta", {**call, "delta": '{"path":"stale.py"}'})
    for _ in range(2):
        record.ingest("tool_call_arguments", {**call, "arguments": '{"path":"actual.py"}'})
    assert len(record.tools) == 1
    assert record.tools[0]["raw_arguments"] == '{"path":"actual.py"}'
    assert record.tools[0]["arguments"] == {"path": "actual.py"}
    assert record.tools[0]["summary"] == '{"path": "actual.py"}'


def test_gpt_snapshots_keep_tools_in_one_uninterrupted_widget_group(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            for index in range(2):
                call = {"turn": index, "tool_call_id": f"call-{index}", "tool_name": "bash"}
                app.on_harness_event(HarnessEvent("tool_call_started", call))
                app.on_harness_event(HarnessEvent("tool_call_delta", {**call, "delta": '{"command":'}))
                for _ in range(2):
                    app.on_harness_event(HarnessEvent("tool_call_arguments", {
                        **call, "arguments": '{"command":"git diff --stat"}',
                    }))
                app.on_harness_event(HarnessEvent("tool_execution_started", {
                    **call, "arguments": {"command": "git diff --stat"},
                }))
                await pilot.pause()
                widget = app._tools[call["tool_call_id"]]
                assert isinstance(widget, ToolCallWidget)
                assert widget.arguments == {"command": "git diff --stat"}
                assert widget.status == "running"
                app.on_harness_event(HarnessEvent("tool_execution_completed", {
                    **call, "status": "success", "result": "1 file changed",
                }))
            app.on_harness_event(HarnessEvent("text_delta", {"delta": "Done"}))
            app._presenter.flush_stream_paints()
            await pilot.pause()
            assert not any("tool_call_arguments" in str(item.render()) for item in app.query(Notice))
            # Bash calls are cards: each mounted once, none folded into a group.
            assert not [item for item in app.query(ToolCallSummary) if item.count]
            assert [item.call_id for item in app.query(BashToolWidget)] == ["call-0", "call-1"]

    asyncio.run(run())


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
            tool_summaries = [
                item for item in screen.query(ToolCallSummary) if item.count
            ]
            assert [item.count for item in tool_summaries] == [11]
            assert not list(screen.query(ToolCallWidget))
            assert [item.message_text for item in screen.query(AssistantMessage)] == ["Child answer"]
            assert app._assistant.parent is not screen.query_one("#transcript")
            emit("run_completed", output_text="Child answer")
            await pilot.pause()
            assert not list(screen.query(ToolCallWidget))
            # Child completion collects work without affecting the parent's cards.
            summary = screen.query_one(CompletedRunSummary)
            assert screen.query_one(ToolCallSummary) is summary
            assert not summary.is_expanded
            assert summary.count == 11
            assert [item.message_text for item in screen.query(AssistantMessage)] == ["Child answer"]
            screen.refresh_record()
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


@pytest.mark.slow
def test_child_view_survives_events_that_banner_above_the_parent_composer(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    endings = (
        ("run_failed", {"message": "boom"}),
        ("run_cancelled", {"reason": "user_cancel"}),
        ("run_limit_exceeded", {"limit": "max_turns"}),
    )

    async def run(ending: str, payload: dict, *, open_first: bool) -> None:
        app = CodingAgentApp(workspace=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            app.add_tool("spawn", "spawn_agent")
            app.on_harness_event(HarnessEvent("agent_spawned", {
                "child_id": "child", "agent_id": "parent", "tool_call_id": "spawn",
                "prompt": "Inspect files", "label": "Inspector", "child_session_id": "child",
            }))
            events = (
                ("run_started", {"model_id": "fake:child"}),
                ("compaction_started", {"message_count": 12}),
                ("compaction_completed", {"before_message_count": 12, "after_message_count": 4}),
                (ending, payload),
            )
            for seq, (name, body) in enumerate(events):
                if open_first and seq == 1:
                    app.open_subagent(app._subagents["child"])
                    await pilot.pause()
                app.on_harness_event(HarnessEvent(name, {
                    **body, "agent_id": "child", "parent_id": "parent",
                    "session_id": "child", "run_id": "run", "seq": seq,
                }))
            if not open_first:
                app.open_subagent(app._subagents["child"])
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SubagentScreen)
            # The child has no composer, so its updates land in its transcript
            # and never reach the parent's banner.
            assert not list(screen.query(ComposerOverlay))
            assert not app.query_one("#composer-overlay", ComposerOverlay).display
            assert any("Compacted context" in item.message_text for item in screen.query(Notice))
            assert screen._process.completed
            assert not screen._busy

    for ending, payload in endings:
        for open_first in (True, False):
            asyncio.run(run(ending, payload, open_first=open_first))


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


def test_ten_closed_subagents_do_not_refresh_parent_cards(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            for index in range(10):
                app.add_tool(f"spawn-{index}", "spawn_agent")
                app.on_harness_event(HarnessEvent("agent_spawned", {
                    "child_id": f"child-{index}", "agent_id": "parent",
                    "tool_call_id": f"spawn-{index}", "label": f"Worker {index}",
                    "prompt": f"Task {index}", "child_session_id": f"child-{index}",
                }))
            await pilot.pause()
            cards = [app._tools[f"spawn-{index}"] for index in range(10)]
            refreshes = {card.call_id: 0 for card in cards}
            for card in cards:
                original = card.refresh_content

                def counted(original=original, card=card):
                    refreshes[card.call_id] += 1
                    return original()

                card.refresh_content = counted
            for index in range(10):
                for seq in range(25):
                    app.on_harness_event(HarnessEvent("text_delta", {
                        "agent_id": f"child-{index}", "parent_id": "parent",
                        "session_id": f"child-{index}", "run_id": f"run-{index}",
                        "seq": index * 25 + seq, "delta": f"word {seq} ",
                    }))
            await pilot.pause()
            assert refreshes == {f"spawn-{index}": 0 for index in range(10)}
            assert all(len(app._subagents[f"child-{index}"].events) == 25 for index in range(10))
            app.open_subagent(app._subagents["child-3"])
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SubagentScreen)
            assert screen.query_one(AssistantMessage).message_text.endswith("word 24 ")
            assert len(app._subagents) == 10

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
