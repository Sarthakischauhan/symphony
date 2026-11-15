"""DurableRunBackend: runs stored as they go, resumed on the same run id and session after a restart."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent
from core_harness import Checkpoint, ControlPlaneEvent, EventSink

from core_server import RunContext, RunExecutor, RunRequest, RunSubmission, build_config
from core_server.durable import RUN_RESUMED, DurableRunBackend, SQLiteDatabase, SQLitePersistence, SQLiteRunStore


class GatedExecutor:
    """Stands in for RunExecutor: emits a step, then finishes when `gate` opens (or until cancelled)."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.seen: list[tuple[str, RunSubmission]] = []

    async def execute(self, run_id: str, submission: RunSubmission, sink: EventSink) -> None:
        self.seen.append((run_id, submission))
        await sink.emit("tool_execution_started", {"tool_name": "shell", "arguments": {}})
        self.started.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            await sink.emit("run_cancelled", {})  # what the harness does when cancelled
            return
        await sink.emit("run_completed", {"output_text": "done"})


def submission(task: str = "open a PR") -> RunSubmission:
    return RunSubmission(RunContext(session_id="s-1", metadata={"thread": "t1"}), RunRequest(message=task))


def backend(db: SQLiteDatabase, executor: Any, **options: Any) -> DurableRunBackend:
    return DurableRunBackend(executor, SQLiteRunStore(db), **options)


def test_finished_runs_and_their_events_outlive_the_process(tmp_path: Path) -> None:
    async def main() -> None:
        executor = GatedExecutor()
        first = backend(SQLiteDatabase(tmp_path / "runs.db"), executor)
        run = await first.submit(submission())
        executor.gate.set()
        assert [event.event_type async for _, event in first.events(run.run_id)][-1] == "run_completed"
        await first.shutdown()

        second = backend(SQLiteDatabase(tmp_path / "runs.db"), GatedExecutor())
        assert await second.recover() == []
        record = await second.get(run.run_id)
        assert record.status == "completed" and record.context.metadata == {"thread": "t1"}
        assert [(n, e.event_type) async for n, e in second.events(run.run_id, after=1)] == [(2, "run_completed")]

    asyncio.run(main())


def test_a_run_stopped_by_shutdown_resumes_with_its_events_continued(tmp_path: Path) -> None:
    async def main() -> None:
        db = SQLiteDatabase(tmp_path / "runs.db")
        executor = GatedExecutor()
        first = backend(db, executor)
        run = await first.submit(submission("fix the flaky test"))
        await executor.started.wait()
        await first.shutdown()
        stored = SQLiteRunStore(db).get(run.run_id)
        assert stored is not None and stored.status == "running"
        # The teardown's own run_cancelled is not recorded: shutting down is not cancelling.
        assert [e.event_type for e in SQLiteRunStore(db).events(run.run_id)] == ["tool_execution_started"]

        again = GatedExecutor()
        second = backend(db, again)
        [resumed] = await second.recover()
        assert resumed.run_id == run.run_id
        await again.started.wait()
        [(_, request)] = again.seen
        assert request.context.session_id == "s-1" and request.request.conversation is None
        assert request.request.message.startswith("[resumed]") and "fix the flaky test" in request.request.message
        again.gate.set()
        events = [(n, e.event_type) async for n, e in second.events(run.run_id)]
        assert events == [(1, "tool_execution_started"), (2, RUN_RESUMED), (3, "tool_execution_started"), (4, "run_completed")]
        stored = SQLiteRunStore(db).get(run.run_id)
        assert stored is not None and stored.status == "completed"

    asyncio.run(main())


def test_runs_that_keep_dying_are_given_up_and_cancelled_runs_stay_cancelled(tmp_path: Path) -> None:
    async def main() -> None:
        db = SQLiteDatabase(tmp_path / "runs.db")
        executor = GatedExecutor()
        first = backend(db, executor, max_attempts=1)
        dying = await first.submit(submission())
        await executor.started.wait()
        await first.shutdown()
        second = backend(db, GatedExecutor(), max_attempts=1)
        assert len(await second.recover()) == 1
        await second.shutdown()
        third = backend(db, GatedExecutor(), max_attempts=1)
        assert await third.recover() == []
        record = await third.get(dying.run_id)
        assert record.status == "failed" and record.events[-1].event_type == "run_failed"

        cancelled_executor = GatedExecutor()
        fourth = backend(db, cancelled_executor)
        cancelled = await fourth.submit(submission())
        await cancelled_executor.started.wait()
        await fourth.cancel(cancelled.run_id)
        stored = SQLiteRunStore(db).get(cancelled.run_id)
        assert stored is not None and stored.status == "cancelled"
        assert await backend(db, GatedExecutor()).recover() == []

    asyncio.run(main())


def test_a_stored_terminal_event_means_the_run_is_over(tmp_path: Path) -> None:
    async def main() -> None:
        store = SQLiteRunStore(SQLiteDatabase(tmp_path / "runs.db"))
        store.insert("r1", submission(), time.time())
        store.set_status("r1", "running")
        store.append_events("r1", 1, [ControlPlaneEvent.typed("run_failed", {"message": "model refused"})])
        executor = GatedExecutor()
        assert await DurableRunBackend(executor, store).recover() == []  # type: ignore[arg-type]
        stored = store.get("r1")
        assert executor.seen == [] and stored is not None and (stored.status, stored.error) == ("failed", "model refused")

    asyncio.run(main())


def test_sqlite_persistence_round_trips_and_prunes(tmp_path: Path) -> None:
    async def main() -> None:
        persistence = SQLitePersistence(SQLiteDatabase(tmp_path / "runs.db"))
        messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
            Message(role="tool", content="ok", tool_call_id="c1"),
        ]
        await persistence.save_conversation(session_id="s", messages=messages)
        await persistence.save_checkpoint(checkpoint=Checkpoint(session_id="s", turn=2, messages=messages))
        reopened = SQLitePersistence(SQLiteDatabase(tmp_path / "runs.db"))
        assert await reopened.load_conversation(session_id="s") == messages
        checkpoint = await reopened.load_checkpoint(session_id="s")
        assert checkpoint is not None and checkpoint.turn == 2
        assert reopened.prune(time.time() + 1) == 1

    asyncio.run(main())


class RestartingRegistry(ModelRegistry):
    """First process: the model never answers. Second process: it answers and we keep what it was sent."""

    def __init__(self, hang: bool) -> None:
        super().__init__()
        self.register("openai", object())  # type: ignore[arg-type]
        self.hang = hang
        self.asked = asyncio.Event()
        self.messages: list[Message] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]], **options: Any):
        self.messages = list(messages)
        self.asked.set()
        if self.hang:
            await asyncio.Event().wait()
        yield StreamEvent(type="text_delta", content_index=0, delta="finished after restart")
        yield StreamEvent(type="done", content_index=0)


def test_the_harness_picks_up_its_stored_conversation_after_a_restart(tmp_path: Path) -> None:
    async def run_server(registry: RestartingRegistry, run_id: str | None) -> tuple[str, str]:
        db = SQLiteDatabase(tmp_path / "runs.db")
        config = build_config(registry=registry, model_id="openai:gpt-test", persistence=SQLitePersistence(db))
        durable = DurableRunBackend(RunExecutor(config), SQLiteRunStore(db))
        if run_id is None:
            run = await durable.submit(RunSubmission(RunContext(session_id="s-9"), RunRequest(message="write the release notes")))
            await registry.asked.wait()
            await durable.shutdown()
            db.close()
            return run.run_id, ""
        [resumed] = await durable.recover()
        events = [event async for _, event in durable.events(resumed.run_id)]
        await durable.shutdown()
        [completed] = [event for event in events if event.event_type == "run_completed"]
        return resumed.run_id, str(completed.payload.get("output_text"))

    async def main() -> None:
        run_id, _ = await run_server(RestartingRegistry(hang=True), None)
        second = RestartingRegistry(hang=False)
        resumed_id, output = await run_server(second, run_id)
        assert resumed_id == run_id and output == "finished after restart"
        users = [str(m.content) for m in second.messages if m.role == "user"]
        assert users[0] == "write the release notes" and users[-1].startswith("[resumed]")

    asyncio.run(main())
