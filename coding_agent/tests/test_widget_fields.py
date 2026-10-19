"""Protocol-3 widget fields: bash exit codes and streams, summaries,
approval metadata, stdio frames and the TUI's use of them."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import pytest
from textual.app import App

from coding_agent.addons.approvals import approval_metadata
from coding_agent.addons.persistence import JsonlPersistence
from coding_agent.protocols import stdio
from coding_agent.widget_fields import SUBAGENT_STEP, EventFields
from coding_agent.protocols.stdio.transport import CAPABILITIES, PROTOCOL_VERSION, StdioSink
from coding_agent.tools.bash import BashTool, CommandFailed
from coding_agent.tools.summary import diff_counts, summarize
from coding_agent.tui.tools.calls import BashToolWidget, PatchDiffWidget, ReadFileWidget, ToolOutcome
from core_harness import EventSink
from core_harness.tools import current_tool_call_id


class Collect(EventSink):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def deliver(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


# bash


def test_bash_nonzero_exit_raises_and_records_exit_code(tmp_path: Path) -> None:
    bash = BashTool(tmp_path)
    tool = bash.as_harness_tool()
    sink = Collect()

    async def run() -> None:
        token = current_tool_call_id.set("call-1")
        with pytest.raises(CommandFailed) as failed:
            await tool.execute(sink=sink, args={"command": "echo out; echo oops >&2; exit 3"})
        current_tool_call_id.reset(token)
        assert failed.value.exit_code == 3
        assert str(failed.value).startswith("exit=3")
        assert bash.exit_codes == {"call-1": 3}

        token = current_tool_call_id.set("call-2")
        ok = await tool.execute(sink=sink, args={"command": "echo fine"})
        current_tool_call_id.reset(token)
        assert "fine" in ok
        assert bash.exit_codes["call-2"] == 0

    asyncio.run(run())
    streams: dict[str, str] = {}
    for event_type, payload in sink.events:
        assert event_type == "tool_execution_output"
        if payload["tool_call_id"] == "call-1":
            streams[payload["stream"]] = streams.get(payload["stream"], "") + payload["delta"]
    assert streams == {"stdout": "out\n", "stderr": "oops\n"}


# summary


def test_summary_counts_per_tool() -> None:
    assert summarize("bash", {}, "a\nb\n") == {"lines": 2, "matches": None, "added": None, "removed": None}
    assert summarize("read_file", {}, "1\n2\n3")["lines"] == 3
    assert summarize("search", {}, "4 content matches\nx")["matches"] == 4
    assert summarize("search", {}, "no content matches")["matches"] == 0
    assert summarize("write_file", {"content": "a\nb"}, "ok")["added"] == 2
    patch = summarize("patch", {"old_str": "a\nb", "new_str": "a\nc\nd"}, "ok")
    assert (patch["added"], patch["removed"]) == (2, 1)
    assert summarize("read_file", {}, "error: x", failed=True)["lines"] is None
    assert diff_counts("", "") == (0, 0)


# approvals


def test_approval_metadata_has_target_detail_bytes() -> None:
    meta = approval_metadata("write_file", {"path": "a.txt", "content": "héllo"}, "Write a.txt?", "c1")
    assert meta["tool_call_id"] == "c1"
    assert set(meta) == {"tool_name", "tool_call_id", "target", "detail", "bytes"}
    assert meta["target"] == "a.txt"
    assert meta["detail"] == "Write a.txt?"
    assert meta["bytes"] == 6
    assert approval_metadata("bash", {"command": "ls"}, "Run?", "c2")["bytes"] is None


# shared enricher


def test_event_fields_enrich_tool_events() -> None:
    fields = EventFields()
    fields.exit_codes["b1"] = 2
    [(_, started)] = fields.apply("tool_execution_started", {
        "tool_call_id": "b1", "tool_name": "bash", "arguments": {"command": "x"}, "started_at": "t0",
    })
    assert started["call_id"] == "b1" and started["parent_call_id"] is None
    [(_, output)] = fields.apply("tool_execution_output", {"tool_call_id": "b1", "delta": "e"})
    assert output["stream"] == "stdout"
    [(_, done)] = fields.apply("tool_execution_completed", {
        "tool_call_id": "b1", "tool_name": "bash", "status": "error", "result": "exit=2\nboom", "duration_ms": 12,
    })
    assert done["exit_code"] == 2
    assert done["summary"]["lines"] == 2
    assert done["duration_ms"] == 12
    assert fields.exit_codes == {"b1": 2}  # read, not popped: the journal reads it too


def test_event_fields_map_subagent_events_to_spawn_call() -> None:
    fields = EventFields()
    [(_, spawned)] = fields.apply("agent_spawned", {
        "child_id": "kid", "tool_call_id": "spawn-1", "agent_id": "root", "session_id": "parent-session",
    })
    assert spawned["parent_call_id"] == "spawn-1"
    events = fields.apply("turn_started", {"agent_id": "kid", "parent_id": "root", "turn": 1, "started_at": "t1"})
    assert [name for name, _ in events] == ["turn_started", SUBAGENT_STEP]
    assert events[1][1] == {
        "session_id": "parent-session", "agent_id": "kid", "parent_id": "root", "parent_call_id": "spawn-1",
        "turn": 1, "started_at": "t1",
    }
    [(_, child_tool)] = fields.apply("tool_execution_started", {"agent_id": "kid", "parent_id": "root", "tool_call_id": "c"})
    assert child_tool["parent_call_id"] == "spawn-1"
    # Output chunks carry no agent ids; the started event's mapping supplies it.
    [(_, chunk)] = fields.apply("tool_execution_output", {"tool_call_id": "c", "delta": "x"})
    assert chunk["parent_call_id"] == "spawn-1"
    assert len(fields.apply("turn_started", {"agent_id": "root", "turn": 1})) == 1


# stdio


def test_stdio_frames_carry_widget_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    frames: list[Mapping[str, Any]] = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    sink = StdioSink()
    assert PROTOCOL_VERSION == 3 and "widget_fields" in CAPABILITIES

    async def run() -> None:
        await sink.deliver("agent_spawned", {"child_id": "kid", "tool_call_id": "spawn-1"})
        await sink.deliver("turn_started", {"agent_id": "kid", "parent_id": "root", "turn": 2, "started_at": "t"})
        await sink.deliver("tool_execution_output", {"tool_call_id": "b", "delta": "x", "stream": "stderr"})
        await sink.deliver("question_asked", {
            "request_id": "r1", "question": "Run ls?", "choices": ["Allow once", "Always allow", "Deny"],
            "default": "Deny", "kind": "approval",
            **approval_metadata("bash", {"command": "ls"}, "Run ls?", "b"),
        })

    asyncio.run(run())
    events = [frame["event"] for frame in frames if frame["type"] == "event"]
    assert events == ["agent_spawned", "turn_started", SUBAGENT_STEP, "tool_execution_output", "question_asked"]
    step = next(frame for frame in frames if frame.get("event") == SUBAGENT_STEP)
    assert step["payload"]["parent_call_id"] == "spawn-1" and step["payload"]["turn"] == 2
    output = next(frame for frame in frames if frame.get("event") == "tool_execution_output")
    assert output["payload"]["stream"] == "stderr"
    [requested] = [frame for frame in frames if frame["type"] == "input_requested"]
    assert requested["metadata"]["tool_call_id"] == "b"
    assert requested["choices"] == ["Allow once", "Always allow", "Deny"]
    assert requested["target"] == "ls"
    assert requested["detail"] == "Run ls?"
    assert requested["bytes"] is None
    assert "options" not in requested and "call_id" not in requested


# TUI


def test_tool_outcome_reads_payload_and_ignores_old_events() -> None:
    outcome = ToolOutcome.from_payload({
        "status": "error", "duration_ms": 1500, "exit_code": 2,
        "summary": {"lines": 1, "matches": None, "added": None, "removed": None},
    })
    assert outcome == ToolOutcome("error", 1500, 2, {"lines": 1, "matches": None, "added": None, "removed": None})
    assert outcome.failed
    assert ToolOutcome.from_payload({"result": "x"}) is None


def test_tui_cards_use_payload_fields() -> None:
    async def run() -> None:
        async with App().run_test():
            bash = BashToolWidget("b", "bash")
            bash.set_running({"command": "make"})
            bash.append_output("ok\n")
            bash.append_output("bad\n", "stderr")
            assert bash._live_tail() == [("stdout", "ok"), ("stderr", "bad")]
            bash.set_result("exit=2\nbad", ToolOutcome("error", 1400, 2, None))
            assert bash.status == "failed" and bash.exit_code == 2
            assert bash.duration == 1.4
            assert bash._header_values == ("Bash", "make", "failed exit 2 · 1.4s")

            old = BashToolWidget("o", "bash")
            old.set_running({"command": "ls"})
            old.set_result("error: nope")
            assert old.status == "failed" and old.exit_code is None and old.duration is not None

            read = ReadFileWidget("r", "read_file")
            read.set_result("a\nb", ToolOutcome("success", 3, None, {"lines": 40, "matches": None, "added": None, "removed": None}))
            assert read._result_summary().startswith("Read 40 lines")

            patch = PatchDiffWidget("p", "patch")
            patch.set_running({"path": "x.py", "old_str": "a", "new_str": "b"})
            patch.set_result("ok", ToolOutcome("success", 3, None, {"lines": None, "matches": None, "added": 5, "removed": 4}))
            assert patch._summary() == "x.py +5 -4"

    asyncio.run(run())


# persistence


def test_journal_keeps_widget_fields(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path)
    store.fields = EventFields()
    store.fields.exit_codes["b1"] = 1
    base = {"session_id": "s1", "run_id": "r1"}

    async def run() -> list[tuple[str, dict[str, Any]]]:
        seq = 0
        for event_type, payload in [
            ("tool_execution_started", {"tool_call_id": "b1", "tool_name": "bash", "arguments": {"command": "x"},
                                        "started_at": 1.0}),
            ("tool_execution_completed", {"tool_call_id": "b1", "tool_name": "bash", "status": "error",
                                          "result": "exit=1\nboom", "duration_ms": 2340}),
            ("question_asked", {"request_id": "q1", "question": "Overwrite?", "choices": ["Allow once"],
                                "default": "Allow once", "kind": "approval", "tool_call_id": "w1",
                                **approval_metadata("write_file", {"path": "a.py", "content": "abc"}, "Overwrite?", "w1")}),
            ("agent_spawned", {"child_id": "kid", "tool_call_id": "s1", "child_session_id": "kid"}),
            ("turn_started", {"agent_id": "kid", "parent_id": "root", "turn": 1, "started_at": 2.0}),
        ]:
            seq += 1
            await store.append_event(event_type=event_type, payload={**base, "seq": seq, **payload})
        return await store.load_events(session_id="s1")

    events = dict((kind, payload) for kind, payload in asyncio.run(run()))
    done = events["tool_execution_completed"]
    assert (done["exit_code"], done["duration_ms"], done["call_id"]) == (1, 2340, "b1")
    assert done["summary"]["lines"] == 2
    assert events["question_asked"]["target"] == "a.py" and events["question_asked"]["bytes"] == 3
    assert events["subagent_step"]["parent_call_id"] == "s1"
    assert events["agent_spawned"]["parent_call_id"] == "s1"
