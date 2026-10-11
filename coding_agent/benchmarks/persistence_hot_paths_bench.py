"""Per-turn cost of the session journal, the reply stream scan, and the diff/@ UI work.

Runs against the checkout this file lives in: ``../src`` goes first on
``sys.path``. Not a test; pytest does not collect it and CI never runs it.

    python coding_agent/benchmarks/persistence_hot_paths_bench.py --turns 10 --turns 50 --turns 200

For each ``--turns N`` it builds N turns of history, then measures ``--samples``
more turns and prints the median of each metric (milliseconds):

  persist   One simulated harness run through ``JsonlPersistence``: user message,
            run/turn/tool lifecycle events through ``append_event``, two
            ``_persist_state`` rounds (``save_conversation`` + ``save_checkpoint``),
            and ``run_completed``. That is what one user turn writes. Message
            bodies are about 1 KB (tool results 4 KB).
  scan      ``EventPresenter._on_text_delta`` over one streamed reply
            (``--reply-chars``, default 8000, in 8-char deltas, ending in a
            "## Spoken summary" section). The handler runs once per delta on
            the UI thread. It does not grow with N, only with the reply length.
  diff_ui   Longest UI event-loop stall while ``/diff`` opens until every
            file card is mounted, in a headless ``CodingAgentApp`` (``App.run_test``). The
            workspace is a git repo of ``--files`` files; every history turn
            edits one tracked file and adds one, so the diff grows with N.
  index_ui  Longest UI event-loop stall from typing ``@mod`` until the file
            menu is filled, right after ``invalidate_workspace_caches`` (what a
            write_file/patch/bash call triggers).

The stall is measured by a 1 ms asyncio ticker in the app's own loop: the
longest gap between ticks, minus the tick. Pure-Python work in a worker
thread still holds the GIL, so a stall is never exactly zero.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock

CHECKOUT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(CHECKOUT_SRC))
os.environ.pop("OPENAI_API_KEY", None)
os.environ["HOME"] = tempfile.mkdtemp(prefix="hot-paths-bench-home-")
os.environ["TEXTUAL_ANIMATIONS"] = "none"

from core_ai.types import Message  # noqa: E402
from core_harness import Checkpoint  # noqa: E402

from coding_agent.addons.persistence.jsonl import JsonlPersistence  # noqa: E402
from coding_agent.tui.app import CodingAgentApp  # noqa: E402
from coding_agent.tui.runtime.events import EventPresenter, TranscriptView  # noqa: E402
from coding_agent.tui.runtime.state import UiRunState  # noqa: E402
from coding_agent.tui.screens.diff import DiffFileCard, DiffModal  # noqa: E402

BODY = "lorem ipsum dolor sit amet " * 38  # ~1 KB
TOOL_BODY = BODY * 4


# --- persistence -----------------------------------------------------------

async def one_run(store: JsonlPersistence, session_id: str, messages: list[Message], turn: int) -> None:
    run_id = f"run-{turn}"
    seq = 0

    async def event(kind: str, **extra: object) -> None:
        nonlocal seq
        seq += 1
        await store.append_event(
            event_type=kind,
            payload={"session_id": session_id, "run_id": run_id, "seq": seq, **extra},
        )

    async def persist(status: str) -> None:
        await store.save_conversation(session_id=session_id, messages=messages)
        await store.save_checkpoint(checkpoint=Checkpoint(
            session_id=session_id, turn=turn, messages=list(messages), status=status,
            metadata={"run_id": run_id},
        ))

    messages.append(Message(role="user", content=f"turn {turn}: {BODY}"))
    await event("run_started", model_id="openai:gpt-test")
    await event("turn_started", turn=0)
    call_id = f"call-{turn}"
    messages.append(Message(role="assistant", content=BODY, tool_calls=[
        {"id": call_id, "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}},
    ]))
    await event("tool_execution_started", call_id=call_id, tool_name="read_file")
    messages.append(Message(role="tool", content=TOOL_BODY, tool_call_id=call_id))
    await event("tool_execution_completed", call_id=call_id, tool_name="read_file", status="success")
    await event("turn_completed", turn=0, had_tool_calls=True)
    await persist("running")
    await event("turn_started", turn=1)
    messages.append(Message(role="assistant", content=f"done {turn}. {BODY}"))
    await event("turn_completed", turn=1, had_tool_calls=False)
    await persist("completed")
    await event("run_completed", output_text="done")


async def bench_persist(turns: int, samples: int) -> list[float]:
    root = Path(tempfile.mkdtemp(prefix="hot-paths-sessions-"))
    store = JsonlPersistence(root)
    store.client = "tui"
    session_id = "bench-session"
    messages: list[Message] = [Message(role="system", content="You are a bench.")]
    for turn in range(turns):
        await one_run(store, session_id, messages, turn)
    times = []
    for turn in range(turns, turns + samples):
        start = perf_counter()
        await one_run(store, session_id, messages, turn)
        times.append((perf_counter() - start) * 1000)
    return times


# --- stream scan -------------------------------------------------------------

def bench_scan(reply_chars: int, samples: int) -> list[float]:
    body = ("The change keeps the journal append-only and the UI responsive. " * 400)[: reply_chars - 120]
    reply = body + "\n\n## Spoken summary\nThe journal now appends; the diff loads in a worker."
    deltas = [reply[i:i + 8] for i in range(0, len(reply), 8)]
    times = []
    for _ in range(samples):
        presenter = EventPresenter(state=UiRunState(), view=Mock(spec=TranscriptView), set_status=lambda _text: None)
        start = perf_counter()
        for delta in deltas:
            presenter._on_text_delta({"delta": delta})
        times.append((perf_counter() - start) * 1000)
    return times


# --- UI thread: /diff and @ index -------------------------------------------------

def make_repo(files: int) -> Path:
    workspace = Path(tempfile.mkdtemp(prefix="hot-paths-ws-"))
    (workspace / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    for index in range(files):
        path = workspace / f"pkg{index % 40}" / f"mod_{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"value_{line} = {line}\n" for line in range(60)), encoding="utf-8")
    git = ["git", "-C", str(workspace), "-c", "user.name=bench", "-c", "user.email=bench@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    return workspace


def edit_turn(workspace: Path, turn: int, files: int) -> None:
    tracked = workspace / f"pkg{turn % 40}" / f"mod_{turn % files}.py"
    with tracked.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"edited_{turn}_{line} = {line}\n" for line in range(20)))
    added = workspace / "pkg_new" / f"new_{turn}.py"
    added.parent.mkdir(exist_ok=True)
    added.write_text(f"created = {turn}\n", encoding="utf-8")


class StallMeter:
    """Longest gap between 1 ms ticks of the app's own event loop."""

    def __init__(self) -> None:
        self.worst = 0.0
        self._task: asyncio.Task[None] | None = None

    async def _tick(self) -> None:
        last = perf_counter()
        while True:
            await asyncio.sleep(0.001)
            now = perf_counter()
            self.worst = max(self.worst, now - last - 0.001)
            last = now

    def start(self) -> None:
        self.worst = 0.0
        self._task = asyncio.get_running_loop().create_task(self._tick())

    async def stop(self) -> float:
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        return max(self.worst, 0.0) * 1000


async def _until(pilot, ready, *, timeout: float = 30.0) -> None:
    deadline = perf_counter() + timeout
    while not ready():
        if perf_counter() > deadline:
            raise TimeoutError("UI never settled")
        await pilot.pause(0.002)


async def bench_ui(turns: int, samples: int, files: int) -> tuple[list[float], list[float]]:
    workspace = make_repo(files)
    for turn in range(turns):
        edit_turn(workspace, turn, files)
    app = CodingAgentApp(workspace=workspace)
    diff_times: list[float] = []
    index_times: list[float] = []
    meter = StallMeter()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        menu = app.query_one("#slash-menu")
        for sample in range(samples):
            edit_turn(workspace, turns + sample, files)
            app.invalidate_workspace_caches()
            await pilot.pause()

            meter.start()
            app.push_screen(DiffModal(workspace))
            await _until(pilot, lambda: isinstance(app.screen, DiffModal) and bool(app.screen._file_data)
                         and len(app.screen.query(DiffFileCard)) == len(app.screen._file_data))
            diff_times.append(await meter.stop())
            app.pop_screen()
            await pilot.pause()

            prompt.value = ""
            await pilot.pause()
            meter.start()
            prompt.value = "Review @mod_1"
            await _until(pilot, lambda: bool(menu.display and menu._files))
            index_times.append(await meter.stop())
            prompt.value = ""
            await pilot.pause()
    return diff_times, index_times


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--turns", type=int, action="append", help="history turns (repeatable)")
    parser.add_argument("--samples", type=int, default=7, help="measured turns per row")
    parser.add_argument("--reply-chars", type=int, default=8000)
    parser.add_argument("--files", type=int, default=3000, help="files in the bench workspace")
    args = parser.parse_args()
    rows = args.turns or [10, 50, 200]
    print(f"checkout: {CHECKOUT_SRC}")
    print(f"samples={args.samples} reply_chars={args.reply_chars} files={args.files}")
    print("| history turns | persist ms/turn | scan ms/reply | diff UI stall ms | @ index UI stall ms |")
    print("|---:|---:|---:|---:|---:|")
    asyncio.run(bench_persist(3, 2))  # warm-up: imports, pydantic schemas
    for turns in rows:
        persist = asyncio.run(bench_persist(turns, args.samples))
        scan = bench_scan(args.reply_chars, args.samples)
        diff_ui, index_ui = asyncio.run(bench_ui(turns, args.samples, args.files))
        print(
            f"| {turns} | {statistics.median(persist):.1f} | {statistics.median(scan):.1f} "
            f"| {statistics.median(diff_ui):.1f} | {statistics.median(index_ui):.1f} |",
            flush=True,
        )


if __name__ == "__main__":
    main()
