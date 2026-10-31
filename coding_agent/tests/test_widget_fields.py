"""Protocol-3 widget fields: bash exit codes and streams, summaries,
approval metadata, stdio frames and the TUI's use of them."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, AsyncGenerator, Mapping

import pytest
from textual.app import App

from coding_agent.addons.approvals import approval_metadata
from coding_agent.addons.persistence import JsonlPersistence
from coding_agent.protocols import stdio
from coding_agent.widget_fields import SUBAGENT_STEP, EventFields
from coding_agent.protocols.stdio.transport import CAPABILITIES, PROTOCOL_VERSION, StdioSink
from coding_agent.tools.ask_user import AskUserTool
from coding_agent.tools.bash import BashTool, CommandFailed
from coding_agent.tools.patch import PatchTool
from coding_agent.tools.read_file import ReadFileTool
from coding_agent.tools.search import SearchTool
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
    assert summarize("bash", {}, "a\nb\n") == {"lines": 2, "matches": None, "added": None, "removed": None, "start_line": None}
    assert summarize("read_file", {}, "1\n2\n3")["lines"] == 3
    # Search matches and the patch start line come from what the tool recorded.
    assert summarize("search", {}, "4 content matches\nx", matches=4)["matches"] == 4
    assert summarize("search", {}, "4 content matches\nx")["matches"] is None
    assert summarize("write_file", {"content": "a\nb"}, "ok")["added"] == 2
    patch = summarize("patch", {"old_str": "a\nb", "new_str": "a\nc\nd"}, "ok")
    assert (patch["added"], patch["removed"]) == (2, 1)
    assert patch["start_line"] is None
    placed = summarize("patch", {"old_str": "a", "new_str": "b"}, "patched a.py at line 42", start_line=42)
    assert placed["start_line"] == 42
    # Result prose is never parsed for it.
    assert summarize("patch", {"old_str": "a", "new_str": "b"}, "patched a.py at line 42")["start_line"] is None
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
    assert PROTOCOL_VERSION >= 3 and "widget_fields" in CAPABILITIES

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


def test_stdio_completed_frames_carry_patch_start_line_and_search_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames: list[Mapping[str, Any]] = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    (tmp_path / "a.py").write_text("".join(f"line {n}\n" for n in range(1, 61)), encoding="utf-8")
    patch, search = PatchTool(tmp_path), SearchTool(tmp_path)
    sink = StdioSink()
    # What EventFields.bind(agent) does with the agent's own tools.
    sink.fields.start_lines, sink.fields.search_hits = patch.start_lines, search.hits

    async def call(call_id: str, tool_name: str, arguments: dict[str, Any], run: Any) -> None:
        await sink.deliver("tool_execution_started", {"tool_call_id": call_id, "tool_name": tool_name,
                                                      "arguments": arguments, "started_at": 1.0})
        token = current_tool_call_id.set(call_id)
        try:
            result = await run.as_harness_tool().execute(sink=None, args=arguments)
        finally:
            current_tool_call_id.reset(token)
        await sink.deliver("tool_execution_completed", {"tool_call_id": call_id, "tool_name": tool_name,
                                                        "status": "success", "result": result, "duration_ms": 3})

    async def run() -> None:
        await call("p1", "patch", {"path": "a.py", "old_str": "line 41\n", "new_str": "LINE 41\n"}, patch)
        await call("s1", "search", {"query": "line 5"}, search)

    asyncio.run(run())
    done = {frame["payload"]["tool_call_id"]: frame["payload"] for frame in frames
            if frame.get("event") == "tool_execution_completed"}
    assert done["p1"]["summary"]["start_line"] == 41
    assert done["p1"]["search_results"] is None
    hits = done["s1"]["search_results"]
    assert hits[0] == {"path": "a.py", "line": 5, "text": "line 5"}
    assert [hit["line"] for hit in hits] == [5, *range(50, 60)]
    assert done["s1"]["summary"]["matches"] == len(hits)



def test_stdio_ask_user_result_is_the_answer_frame_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The completed ask_user `result` is the value of the host's answer frame."""
    from core_ai.providers.base import BaseProvider
    from core_ai.registry import ModelRegistry
    from core_ai.types import Message, StreamEvent
    from core_harness import Answer, CoreHarness, HarnessConfig

    turns = [
        [
            StreamEvent(type="toolcall_start", content_index=0, tool_call_id="ask-1", tool_name="ask_user"),
            StreamEvent(type="toolcall_delta", content_index=0, delta='{"question": "Units?", "activity": {"verb": "Asking", "reason": "Need the units."}}'),
            StreamEvent(type="done"),
        ],
        [StreamEvent(type="text_delta", delta="ok"), StreamEvent(type="done")],
    ]

    class Scripted(BaseProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def stream(
            self,
            model_name: str,
            messages: list[Message],
            tools: list[dict[str, Any]] = [],
            max_output_tokens: int | None = None,
            reasoning_effort: str | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> AsyncGenerator[StreamEvent, None]:
            del model_name, messages, tools, max_output_tokens, reasoning_effort, extra_headers
            turn = turns[min(self.calls, len(turns) - 1)]
            self.calls += 1
            for event in turn:
                yield event

    registry = ModelRegistry()
    registry.register("fake", Scripted())
    harness: list[CoreHarness] = []
    frames: list[Mapping[str, Any]] = []

    def write(frame: Mapping[str, Any]) -> None:
        frames.append(frame)
        # What the host's `{"type":"answer","request_id",...,"value"}` frame submits.
        if frame.get("type") == "input_requested":
            assert harness[0].submit(Answer(str(frame["request_id"]), "  Metric  "))

    monkeypatch.setattr(stdio, "write_frame", write)
    sink = StdioSink()
    harness.append(CoreHarness(
        registry=registry,
        model_id="fake:ask",
        system_prompt="test",
        config=HarnessConfig(max_turns=3),
        tools=[AskUserTool(str(tmp_path)).as_harness_tool()],
        sink=sink,
    ))
    asyncio.run(harness[0].run("go"))
    events = {frame["event"]: frame["payload"] for frame in frames if frame.get("type") == "event"}
    asked = next(frame for frame in frames if frame.get("type") == "input_requested")
    assert asked["metadata"] == {"tool_call_id": "ask-1"}
    done = events["tool_execution_completed"]
    assert (done["tool_call_id"], done["status"], done["result"]) == ("ask-1", "success", "Metric")



def test_read_file_records_start_line_from_offset(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("".join(f"line {n}\n" for n in range(1, 61)), encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ))
    read = ReadFileTool(tmp_path)

    async def call(call_id: str, args: dict[str, Any]) -> object:
        token = current_tool_call_id.set(call_id)
        try:
            return await read.execute(sink=None, args=args)
        finally:
            current_tool_call_id.reset(token)

    async def run() -> list[object]:
        return [
            await call("r41", {"path": "a.py", "offset": 41, "limit": 2}),
            await call("r1", {"path": "a.py", "limit": 1}),
            await call("missing", {"path": "nope.py"}),
            await call("past-end", {"path": "a.py", "offset": 99}),
            await call("image", {"path": "shot.png"}),
        ]

    results = asyncio.run(run())
    assert results[0] == "  41|line 41\n  42|line 42\n"
    # Only numbered text reads record a start line; it is the read's offset.
    assert read.start_lines == {"r41": 41, "r1": 1}


def test_read_file_start_line_reaches_stdio_frames_and_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core_ai.providers.base import BaseProvider
    from core_ai.registry import ModelRegistry
    from core_ai.types import Message, StreamEvent

    from coding_agent import CodingAgent
    from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig

    (tmp_path / "a.py").write_text("".join(f"line {n}\n" for n in range(1, 61)), encoding="utf-8")
    activity = '"activity": {"verb": "Reading", "reason": "Check the numbered lines."}'
    calls = [
        ("r41", '{"path": "a.py", "offset": 41, "limit": 2, ' + activity + "}"),
        ("gone", '{"path": "nope.py", ' + activity + "}"),
    ]
    turns = [
        [
            *(
                event
                for index, (call_id, args) in enumerate(calls)
                for event in (
                    StreamEvent(type="toolcall_start", content_index=index, tool_call_id=call_id,
                                tool_name="read_file"),
                    StreamEvent(type="toolcall_delta", content_index=index, delta=args),
                )
            ),
            StreamEvent(type="done"),
        ],
        [StreamEvent(type="text_delta", delta="ok"), StreamEvent(type="done")],
    ]

    class Scripted(BaseProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def stream(
            self,
            model_name: str,
            messages: list[Message],
            tools: list[dict[str, Any]] = [],
            max_output_tokens: int | None = None,
            reasoning_effort: str | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> AsyncGenerator[StreamEvent, None]:
            del model_name, messages, tools, max_output_tokens, reasoning_effort, extra_headers
            turn = turns[min(self.calls, len(turns) - 1)]
            self.calls += 1
            for event in turn:
                yield event

    registry = ModelRegistry()
    registry.register("fake", Scripted())
    frames: list[Mapping[str, Any]] = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    sink = StdioSink()
    agent = CodingAgent(
        registry=registry,
        model_id="fake:read",
        workspace=tmp_path,
        sink=sink,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False), langfuse=LangfuseConfig(enabled=False), unattended=True
        ),
    )
    # What the stdio server, the TUI and the session store each do.
    sink.fields.bind(agent)
    emitted: list[tuple[str, dict[str, Any]]] = []
    sink.subscribe(lambda name, body: emitted.append((name, dict(body))))
    asyncio.run(agent.run("read"))

    done = {frame["payload"]["tool_call_id"]: frame["payload"] for frame in frames
            if frame.get("event") == "tool_execution_completed"}
    assert done["r41"]["result"] == "  41|line 41\n  42|line 42\n"
    assert done["r41"]["summary"]["start_line"] == 41
    assert done["gone"]["summary"]["start_line"] is None

    store = JsonlPersistence(tmp_path / "store")
    store.fields = EventFields()
    store.fields.bind(agent)
    base = {"session_id": "s1", "run_id": "r1"}

    async def journal() -> list[tuple[str, dict[str, Any]]]:
        tool_events = [(name, body) for name, body in emitted if name.startswith("tool_execution_")]
        for seq, (name, body) in enumerate(tool_events, start=1):
            await store.append_event(event_type=name, payload={**base, "seq": seq, **body, "session_id": "s1"})
        return await store.load_events(session_id="s1")

    kept = {payload["tool_call_id"]: payload for kind, payload in asyncio.run(journal())
            if kind == "tool_execution_completed"}
    assert kept["r41"]["summary"]["start_line"] == 41


# TUI


def test_tool_outcome_reads_payload_and_ignores_old_events() -> None:
    outcome = ToolOutcome.from_payload({
        "status": "error", "duration_ms": 1500, "exit_code": 2,
        "summary": {"lines": 1, "matches": None, "added": None, "removed": None},
    })
    # An older summary without start_line reads it as None.
    assert outcome == ToolOutcome(
        "error", 1500, 2, {"lines": 1, "matches": None, "added": None, "removed": None, "start_line": None}
    )
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
            read.set_result("a\nb", ToolOutcome("success", 3, None, {"lines": 40, "matches": None, "added": None, "removed": None, "start_line": None}))
            assert read._result_summary().startswith("Read 40 lines")

            patch = PatchDiffWidget("p", "patch")
            patch.set_running({"path": "x.py", "old_str": "a", "new_str": "b"})
            patch.set_result(
                "ok", ToolOutcome("success", 3, None, {"lines": None, "matches": None, "added": 5, "removed": 4, "start_line": 30})
            )
            assert patch._summary() == "x.py +5 -4"
            # The card's hunk header uses the file line from summary.start_line.
            assert patch._diff()[0] == "@@ -30 +30 @@"
            # Without a summary the card does not read the line out of the result text.
            live = PatchDiffWidget("q", "patch")
            live.set_running({"path": "y.py", "old_str": "a", "new_str": "b"})
            live.set_result("patched y.py at line 7 (1 replacement(s), +0 bytes)")
            assert live._diff()[0] == "@@ -1 +1 @@"

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
