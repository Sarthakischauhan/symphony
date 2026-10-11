"""Per-turn journal work stays O(new entries), on-disk bytes stay the same.

``fixtures/sessions/recorded-session`` was written by ``record_session`` below
running against main@f214da7 (before this change), with the clock pinned. The
branch must write the same bytes and keep loading and resuming that bundle.
"""

from __future__ import annotations

import asyncio
import json
import random
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from core_ai.types import Message
from core_harness import Checkpoint
from core_harness.context import COMPACTED_CONTEXT_MARK

import coding_agent.addons.persistence.artifacts as artifacts
import coding_agent.addons.persistence.jsonl as jsonl
from coding_agent.addons.persistence.jsonl import JsonlPersistence
from coding_agent.addons.voice.summary import SpokenSummaryStream, split_spoken_summary
from coding_agent.tui.runtime.events import EventPresenter, TranscriptView
from coding_agent.tui.runtime.state import UiRunState

FIXTURE = Path(__file__).parent / "fixtures" / "sessions" / "recorded-session"
SESSION = "recorded-session"
FIXED_NOW = "2026-10-11T12:00:00+00:00"


async def record_session(store: JsonlPersistence, session_id: str = SESSION) -> None:
    """Three tool-using runs, a spawned child, then a compaction rewrite."""
    store.client = "tui"
    msgs = [Message(role="system", content="You are Symphony.")]
    for turn in range(3):
        run_id = f"run-{turn}"
        seq = 0

        async def event(kind: str, **extra: object) -> None:
            nonlocal seq
            seq += 1
            await store.append_event(event_type=kind, payload={
                "session_id": session_id, "run_id": run_id, "seq": seq,
                "ts": 1760000000.0 + turn, **extra,
            })

        msgs.append(Message(role="user", content=f"Question {turn}"))
        await event("run_started", model_id="openai:gpt-test")
        await event("turn_started", turn=0)
        msgs.append(Message(role="assistant", content="", tool_calls=[{
            "id": f"c{turn}", "type": "function",
            "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"},
        }]))
        await event("tool_execution_started", call_id=f"c{turn}", tool_name="read_file")
        msgs.append(Message(role="tool", content=f"contents {turn}", tool_call_id=f"c{turn}"))
        await event("tool_execution_completed", call_id=f"c{turn}", tool_name="read_file", status="success")
        if turn == 1:
            await event("agent_spawned", child_id="child-1", child_session_id="child-session", parent_id="root")
            await event("agent_completed", child_id="child-1", output_text="child done")
        await event("turn_completed", turn=0, had_tool_calls=True)
        await store.save_conversation(session_id=session_id, messages=msgs)
        await store.save_checkpoint(checkpoint=Checkpoint(
            session_id=session_id, turn=turn, messages=list(msgs), status="running",
            metadata={"run_id": run_id},
        ))
        msgs.append(Message(role="assistant", content=f"Answer {turn}"))
        await store.save_conversation(session_id=session_id, messages=msgs)
        await store.save_checkpoint(checkpoint=Checkpoint(
            session_id=session_id, turn=turn, messages=list(msgs), status="completed",
            metadata={"run_id": run_id},
        ))
        await event("run_completed", output_text=f"Answer {turn}")
        await store.annotate_run_completed(
            session_id=session_id, run_id=run_id, completion_verb="Worked",
            duration="1s", elapsed_seconds=1.0,
        )
    msgs = [
        msgs[0],
        Message(role="user", content=f"{COMPACTED_CONTEXT_MARK}\nSummary of earlier work."),
        Message(role="user", content="Question 3"),
        Message(role="assistant", content="Answer 3"),
    ]
    await store.save_conversation(session_id=session_id, messages=msgs)
    await store.save_checkpoint(checkpoint=Checkpoint(
        session_id=session_id, turn=4, messages=list(msgs), status="completed",
        metadata={"goal": "ship it"},
    ))


def _bundle_files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != ".lock"
    }


@pytest.fixture
def recorded(tmp_path: Path) -> Path:
    root = tmp_path / "sessions"
    shutil.copytree(FIXTURE, root / SESSION)
    return root


def test_journal_and_artifacts_are_byte_identical_to_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(jsonl, "_utc_now", lambda: FIXED_NOW)
    store = JsonlPersistence(tmp_path)
    asyncio.run(record_session(store))
    assert _bundle_files(tmp_path / SESSION) == _bundle_files(FIXTURE)


def test_existing_session_round_trips(recorded: Path) -> None:
    store = JsonlPersistence(recorded)

    conversation = asyncio.run(store.load_conversation(session_id=SESSION))
    transcript = asyncio.run(store.load_transcript(session_id=SESSION))
    checkpoint = asyncio.run(store.load_checkpoint(session_id=SESSION))
    events = asyncio.run(store.load_events(session_id=SESSION))
    children = asyncio.run(store.load_children(parent_session_id=SESSION))
    compactions = asyncio.run(store.load_compactions(SESSION))

    assert [m.content for m in conversation] == [
        "You are Symphony.",
        f"{COMPACTED_CONTEXT_MARK}\nSummary of earlier work.",
        "Question 3",
        "Answer 3",
    ]
    # The full history survives compaction for the TUI.
    assert [m.content for m in transcript if m.role == "user"][:3] == [
        "Question 0", "Question 1", "Question 2",
    ]
    assert checkpoint is not None and checkpoint.metadata == {"goal": "ship it"}
    assert checkpoint.turn == 4
    assert [child["child_id"] for child in children] == ["child-1"]
    assert children[0]["status"] == "completed"
    assert len(compactions) == 1
    collected = [payload for kind, payload in events if kind == "tool_execution_started"]
    assert collected and all(payload.get("collected") is True for payload in collected)
    # Reading an intact bundle repairs nothing.
    assert _bundle_files(recorded / SESSION) == _bundle_files(FIXTURE)


def test_resuming_an_existing_session_only_appends(recorded: Path) -> None:
    transcript = recorded / SESSION / "transcript.jsonl"
    before = transcript.read_bytes()
    store = JsonlPersistence(recorded)
    messages = asyncio.run(store.load_conversation(session_id=SESSION))
    messages += [Message(role="user", content="Question 4"), Message(role="assistant", content="Answer 4")]

    asyncio.run(store.save_conversation(session_id=SESSION, messages=messages))

    after = transcript.read_bytes()
    assert after.startswith(before)
    added = [json.loads(line) for line in after[len(before):].decode().splitlines()]
    assert [entry["content"] for entry in added] == ["Question 4", "Answer 4"]
    assert [entry["seq"] for entry in added] == [39, 40]  # what main writes too
    reloaded = asyncio.run(JsonlPersistence(recorded).load_conversation(session_id=SESSION))
    assert [m.content for m in reloaded][-2:] == ["Question 4", "Answer 4"]


async def _turns(store: JsonlPersistence, session_id: str, count: int, messages: list[Message]) -> None:
    for turn in range(count):
        messages.append(Message(role="user", content=f"q{turn}"))
        messages.append(Message(role="assistant", content=f"a{turn}"))
        await store.save_conversation(session_id=session_id, messages=messages)
        await store.save_checkpoint(checkpoint=Checkpoint(
            session_id=session_id, turn=turn, messages=list(messages), status="completed",
        ))


@pytest.mark.parametrize("history", [5, 60])
def test_per_turn_work_does_not_grow_with_history(tmp_path: Path, monkeypatch, history: int) -> None:
    store = JsonlPersistence(tmp_path)
    messages = [Message(role="system", content="s")]
    asyncio.run(_turns(store, "long", history, messages))

    published: list[str] = []
    parsed: list[Path] = []
    real_publish = artifacts.publish
    real_load = JsonlPersistence._load_transcript

    def counting_publish(path: Path, payload: bytes) -> None:
        published.append(path.name)
        real_publish(path, payload)

    def counting_load(self: JsonlPersistence, path: Path):
        parsed.append(path)
        return real_load(self, path)

    monkeypatch.setattr(artifacts, "publish", counting_publish)
    monkeypatch.setattr(JsonlPersistence, "_load_transcript", counting_load)
    asyncio.run(_turns(store, "long", 3, messages))

    # Per turn: one append from save_conversation and one from save_checkpoint,
    # each refreshing metadata.json; the checkpoint also publishes checkpoint.json.
    # Same count at 5 turns of history as at 60.
    assert sorted(published) == sorted(["metadata.json"] * 6 + ["checkpoint.json"] * 3)
    assert parsed == []


def test_torn_last_line_from_a_crash_does_not_swallow_the_next_record(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path)
    messages = [Message(role="system", content="s"), Message(role="user", content="before crash")]
    asyncio.run(store.save_conversation(session_id="torn", messages=messages))
    transcript = tmp_path / "torn" / "transcript.jsonl"
    with transcript.open("ab") as handle:  # a crash mid-append: no newline
        handle.write(b'{"type": "message", "event_type": "assistant", "seq": 3, "mess')

    resumed = JsonlPersistence(tmp_path)
    loaded = asyncio.run(resumed.load_conversation(session_id="torn"))
    assert [m.content for m in loaded] == ["s", "before crash"]
    loaded.append(Message(role="assistant", content="after crash"))
    asyncio.run(resumed.save_conversation(session_id="torn", messages=loaded))

    lines = transcript.read_bytes().split(b"\n")
    assert lines[-2].startswith(b'{"type": "message"') and b"after crash" in lines[-2]
    assert lines[-3].endswith(b'"mess')  # the fragment stays one skipped line
    fresh = asyncio.run(JsonlPersistence(tmp_path).load_conversation(session_id="torn"))
    assert [m.content for m in fresh] == ["s", "before crash", "after crash"]


def test_artifacts_left_stale_by_a_crash_are_repaired_on_the_next_read(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path)
    messages = [Message(role="system", content="s")]
    asyncio.run(_turns(store, "stale", 2, messages))
    directory = tmp_path / "stale"
    expected = (directory / "checkpoint.json").read_bytes()
    # A crash after the checkpoint line was appended, before checkpoint.json.
    (directory / "checkpoint.json").write_text('{"turn": 0}\n', encoding="utf-8")

    resumed = JsonlPersistence(tmp_path)
    asyncio.run(resumed.save_conversation(session_id="stale", messages=messages))
    assert (directory / "checkpoint.json").read_bytes() == expected

    (directory / "checkpoint.json").unlink()
    asyncio.run(JsonlPersistence(tmp_path).collect_run_events(session_id="stale"))
    assert (directory / "checkpoint.json").read_bytes() == expected


def test_another_writer_invalidates_the_cached_journal(tmp_path: Path) -> None:
    first = JsonlPersistence(tmp_path)
    second = JsonlPersistence(tmp_path)
    messages = [Message(role="system", content="s"), Message(role="user", content="one")]
    asyncio.run(first.save_conversation(session_id="shared", messages=messages))
    messages.append(Message(role="assistant", content="two"))
    asyncio.run(second.save_conversation(session_id="shared", messages=messages))
    messages.append(Message(role="user", content="three"))
    asyncio.run(first.save_conversation(session_id="shared", messages=messages))

    entries = [json.loads(line) for line in (tmp_path / "shared" / "transcript.jsonl").read_text().splitlines()]
    contents = [entry.get("content") for entry in entries if entry.get("type") == "message"]
    assert contents == ["s", "one", "two", "three"]
    assert [entry["seq"] for entry in entries] == [1, 2, 3, 4, 5]


# --- streamed spoken-summary split ---------------------------------------------

_PIECES = [
    "Hello ", "world. ", "## Spoken summary", "## spoken SUMMARY", "## Spo", "\n", "  ",
    "\n\n", "## ", "##", "#", " Spoken", " summary", "ΣΑΣ ", "İ", "é", "…",
    "```\ncode\n```", "done.", "\t",
]


def test_streamed_split_matches_the_whole_text_split_at_every_delta() -> None:
    rng = random.Random(20261011)
    for _ in range(3000):
        blob = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 25)))
        stream = SpokenSummaryStream()
        text = ""
        index = 0
        while index < len(blob):
            size = rng.randint(1, 6)
            text += blob[index:index + size]
            index += size
            assert stream.visible(text) == split_spoken_summary(text)[0], repr(text)


def test_streamed_split_starts_over_when_the_reply_restarts() -> None:
    stream = SpokenSummaryStream()
    assert stream.visible("Long answer.\n\n## Spoken summary\nSay this.") == "Long answer."
    assert stream.visible("Retry") == "Retry"
    assert stream.visible("Retry\n## Spo") == "Retry"


def _painted(view: Mock) -> list[str]:
    return [call.args[0] for call in view.set_assistant.call_args_list]


def test_presenter_paints_what_the_whole_text_split_would() -> None:
    reply = "Renamed the helper.\n\n## Spo" + "ken summary\nI renamed it."
    view = Mock(spec=TranscriptView)
    presenter = EventPresenter(state=UiRunState(), view=view, set_status=lambda _text: None)
    expected = []
    text = ""
    for start in range(0, len(reply), 3):
        delta = reply[start:start + 3]
        text += delta
        presenter.handle("text_delta", {"delta": delta})
        presenter.flush_stream_paints()
        expected.append(split_spoken_summary(text)[0])
    assert _painted(view)[-1] == "Renamed the helper."
    assert set(_painted(view)) <= set(expected)

    presenter.handle("model_retry_scheduled", {"resets_stream": True, "retry_after": 1})
    presenter.handle("text_delta", {"delta": "Fresh"})
    presenter.flush_stream_paints()
    assert _painted(view)[-1] == "Fresh"
