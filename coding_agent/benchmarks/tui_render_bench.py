"""Headless TUI render benchmark for grouped (Explored) tool rows.

Runs against the checkout this file lives in: ``../src`` goes first on
``sys.path``. Not a test; pytest does not collect it and CI never runs it.

    python coding_agent/benchmarks/tui_render_bench.py --rows 50 --rows 200

Each run builds a fresh ``CodingAgentApp`` under ``App.run_test`` and mounts a
fixed transcript: ``--rows`` tool rows (read_file/search) in Explored groups of
``--group`` rows, each group closed by an assistant line, every group expanded.
Then it times, with ``time.perf_counter``:

  mount     mount the fixture, expand every group, wait for the first refresh
  append    append one finished tool row to the live transcript and repaint
  toggle    collapse plus expand one Explored group, repainting after each
  relayout  full relayout of the screen and repaint
  scroll    scroll the transcript to the top, then to the end, repainting

``--live`` measures a streamed turn instead (``--tools`` repeatable, default
10 and 50): five prior turns of history, then one live turn whose tool calls
(read_file, search and every third a bash call) each go started -> running ->
done through the event presenter, with assistant text chunks after every five
calls, then run end. Bash calls stream output chunks between running and done
when the checkout handles ``tool_execution_output``. Per tool call it reports
the wall time of one lifecycle update (event plus repaint), the transcript
rebuild passes (``reconcile_live_tools`` calls, where that path exists), the
``refresh(layout=True)`` requests (all, and those on mounted widgets) and
widgets mounted/removed (counted the way the render repro's churn probe does),
and the screen layout passes; per output chunk, its time, relayout requests
and mounts; plus the run-end time.

Animations are off (``TEXTUAL_ANIMATIONS=none``) so row fade-ins do not count.
The first run is a warm-up and is discarded. Times are in milliseconds.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

CHECKOUT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(CHECKOUT_SRC))
os.environ.pop("OPENAI_API_KEY", None)
os.environ["HOME"] = tempfile.mkdtemp(prefix="tui-bench-home-")
# Fade/settle animations would otherwise put their 0.12-0.18 s durations into
# the timings; with animations off Textual finishes them immediately.
os.environ["TEXTUAL_ANIMATIONS"] = "none"

from textual.containers import VerticalScroll  # noqa: E402
from textual.pilot import Pilot  # noqa: E402
from textual.screen import Screen  # noqa: E402
from textual.widget import Widget  # noqa: E402

from coding_agent.tui.app import CodingAgentApp  # noqa: E402
from coding_agent.tui.composer import QueuedTurn  # noqa: E402
from coding_agent.tui.runtime.events import EventPresenter  # noqa: E402
from coding_agent.tui.tools.snapshots import ToolCallSummary  # noqa: E402
from coding_agent.tui.transcript import surface as transcript_surface  # noqa: E402

try:
    from coding_agent.tui.transcript.live_tools import reconcile_live_tools  # noqa: E402
except ImportError:  # removed when the transcript started updating rows in place
    reconcile_live_tools = None

SIZE = (110, 40)
METRICS = ("mount", "append", "toggle", "relayout", "scroll")
TOOLS = (
    ("read_file", lambda index: {"path": f"src/pkg/module_{index}.py"}),
    ("search", lambda index: {"query": f"symbol_{index}"}),
)


@dataclass
class Samples:
    times: dict[str, list[float]] = field(default_factory=lambda: {name: [] for name in METRICS})

    def add(self, name: str, seconds: float) -> None:
        self.times[name].append(seconds * 1000)


def add_finished_tool(app: CodingAgentApp, call_id: str, index: int) -> None:
    name, arguments = TOOLS[index % len(TOOLS)]
    app.add_tool(call_id, name)
    app.update_tool(call_id, arguments=arguments(index), status="running")
    app.update_tool(call_id, status="done", result="ok")


def mount_fixture(app: CodingAgentApp, rows: int, group: int) -> None:
    for index in range(rows):
        add_finished_tool(app, f"call-{index}", index)
        if (index + 1) % group == 0 or index + 1 == rows:
            app.set_assistant(f"Checked batch {index // group}.", new=True)


def expand_all(app: CodingAgentApp) -> list[ToolCallSummary]:
    summaries = list(app.query(ToolCallSummary))
    for summary in summaries:
        if not summary.is_expanded:
            summary.toggle()
    return summaries


async def run_once(rows: int, group: int, samples: Samples | None) -> tuple[int, int]:
    workspace = Path(tempfile.mkdtemp(prefix="tui-bench-ws-"))
    app = CodingAgentApp(workspace=workspace)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()

        start = perf_counter()
        mount_fixture(app, rows, group)
        await pilot.pause()
        summaries = expand_all(app)
        await pilot.pause()
        mount = perf_counter() - start

        start = perf_counter()
        add_finished_tool(app, "call-appended", rows)
        await pilot.pause()
        append = perf_counter() - start

        target = summaries[len(summaries) // 2]
        start = perf_counter()
        target.toggle()
        await pilot.pause()
        target.toggle()
        await pilot.pause()
        toggle = perf_counter() - start

        start = perf_counter()
        app.screen.refresh(layout=True)
        await pilot.pause()
        relayout = perf_counter() - start

        transcript = app.query_one("#transcript", VerticalScroll)
        start = perf_counter()
        transcript.scroll_home(animate=False)
        await pilot.pause()
        transcript.scroll_end(animate=False)
        await pilot.pause()
        scroll = perf_counter() - start

        expanded_rows = sum(summary.count for summary in summaries if summary.is_expanded)
        if samples is not None:
            for name, seconds in zip(METRICS, (mount, append, toggle, relayout, scroll)):
                samples.add(name, seconds)
        return len(summaries), expanded_rows


def summarise(rows: int, samples: Samples, *, raw: bool) -> None:
    for name in METRICS:
        values = samples.times[name]
        print(
            f"rows={rows:<4} {name:<9} median={statistics.median(values):8.1f} ms"
            f"  min={min(values):8.1f}  max={max(values):8.1f}  n={len(values)}"
        )
        if raw:
            print(f"raw rows={rows} {name} " + " ".join(f"{value:.2f}" for value in values))


async def bench(rows: int, group: int, runs: int, *, raw: bool) -> None:
    groups, expanded = await run_once(rows, group, None)
    print(f"rows={rows} groups={groups} expanded_rows={expanded} (warm-up discarded)")
    samples = Samples()
    for _ in range(runs):
        await run_once(rows, group, samples)
    summarise(rows, samples, raw=raw)


LIVE_METRICS = (
    "ms/update",
    "rebuilds/call",
    "relayouts/call",
    "mounted-relayouts/call",
    "layouts/call",
    "mounted/call",
    "removed/call",
    "ms/output-chunk",
    "relayouts/output-chunk",
    "mounted/output-chunk",
    "run-end ms",
)
LIVE_TOOLS = (*TOOLS, ("bash", lambda index: {"command": f"pytest -q tests/test_{index}.py"}))
OUTPUT_CHUNKS = 8
# Checkouts before the live Bash card have no handler for output chunks (the
# presenter would post each one as a notice), so the bench only sends them
# where the presenter defines one.
STREAMS_OUTPUT = "_on_tool_execution_output" in vars(EventPresenter)
HISTORY_TURNS = 5
HISTORY_TOOLS = 6
TEXT_EVERY = 5
TEXT_CHUNKS = 3
COUNTS: collections.Counter[str] = collections.Counter()


def count_render_work() -> None:
    """Count mounts, removals, layout requests and layout passes (bench only)."""
    mount, remove, refresh = Widget.mount, Widget.remove, Widget.refresh
    layout = Screen._refresh_layout

    def counted_mount(self: Widget, *widgets: Widget, **kwargs: Any) -> Any:
        COUNTS["mounted"] += len(widgets)
        return mount(self, *widgets, **kwargs)

    def counted_remove(self: Widget) -> Any:
        COUNTS["removed"] += 1
        return remove(self)

    def counted_refresh(self: Widget, *args: Any, layout: bool = False, **kwargs: Any) -> Any:
        COUNTS["relayouts"] += layout
        COUNTS["mounted-relayouts"] += layout and self.is_mounted
        return refresh(self, *args, layout=layout, **kwargs)

    def counted_layout(self: Screen[Any], *args: Any, **kwargs: Any) -> None:
        COUNTS["layouts"] += 1
        layout(self, *args, **kwargs)

    Widget.mount, Widget.remove, Widget.refresh = counted_mount, counted_remove, counted_refresh
    Screen._refresh_layout = counted_layout
    if reconcile_live_tools is not None:
        rebuild = reconcile_live_tools

        def counted_rebuild(*args: Any, **kwargs: Any) -> Any:
            COUNTS["rebuilds"] += 1
            return rebuild(*args, **kwargs)

        transcript_surface.reconcile_live_tools = counted_rebuild


def start_turn(app: CodingAgentApp, prompt: str) -> Callable[[str, dict[str, Any]], None]:
    """Open a turn the way the composer does, and return its event feed."""
    app._start_turn(QueuedTurn(prompt, prompt, (), ()))
    assert app._presenter is not None
    handle = app._presenter.handle
    handle("run_started", {"model_id": "bench:model"})
    handle("turn_started", {"turn": 0, "message_count": 2})
    return handle


def live_tool(index: int) -> tuple[str, Callable[[int], dict[str, Any]]]:
    return LIVE_TOOLS[index % len(LIVE_TOOLS)]


def tool_events(call_id: str, index: int) -> list[tuple[str, dict[str, Any]]]:
    name, arguments = live_tool(index)
    call = {"tool_call_id": call_id, "tool_name": name}
    return [
        ("tool_call_started", call),
        ("tool_execution_started", {**call, "arguments": arguments(index)}),
        ("tool_execution_completed", {**call, "result": "ok", "status": "success"}),
    ]


def output_events(call_id: str, index: int) -> list[tuple[str, dict[str, Any]]]:
    if live_tool(index)[0] != "bash" or not STREAMS_OUTPUT:
        return []
    return [
        ("tool_execution_output", {"tool_call_id": call_id, "delta": f"tests/test_{index}.py::case_{chunk} PASSED\n"})
        for chunk in range(OUTPUT_CHUNKS)
    ]


def stream_text(app: CodingAgentApp, handle: Callable[[str, dict[str, Any]], None], batch: int) -> None:
    for chunk in range(TEXT_CHUNKS):
        handle("text_delta", {"turn": 0, "delta": f"Batch {batch}, note {chunk}. "})
    assert app._presenter is not None
    app._presenter.flush_stream_paints()


async def history(app: CodingAgentApp, pilot: Pilot[None]) -> None:
    for turn in range(HISTORY_TURNS):
        handle = start_turn(app, f"earlier question {turn}")
        for index in range(HISTORY_TOOLS):
            for event, payload in tool_events(f"h{turn}-{index}", index):
                handle(event, payload)
        stream_text(app, handle, turn)
        handle("run_completed", {"output_text": f"Earlier answer {turn}."})
        await pilot.pause()


async def timed_event(
    handle: Callable[[str, dict[str, Any]], None],
    pilot: Pilot[None],
    event: str,
    payload: dict[str, Any],
    totals: collections.Counter[str],
) -> float:
    """Send one event, wait for the repaint; count its render work into ``totals``."""
    COUNTS.clear()
    start = perf_counter()
    handle(event, payload)
    await pilot.pause()
    elapsed = perf_counter() - start
    totals.update(COUNTS)
    return elapsed


async def run_live_once(tools: int) -> dict[str, float]:
    workspace = Path(tempfile.mkdtemp(prefix="tui-bench-ws-"))
    app = CodingAgentApp(workspace=workspace)
    app.run_agent = lambda content: None  # the bench feeds events itself
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await history(app, pilot)
        handle = start_turn(app, "the live question")
        await pilot.pause()
        totals: collections.Counter[str] = collections.Counter()
        chunk_totals: collections.Counter[str] = collections.Counter()
        update_seconds = chunk_seconds = 0.0
        chunks = 0
        for index in range(tools):
            started, running, done = tool_events(f"live-{index}", index)
            for event, payload in (started, running):
                update_seconds += await timed_event(handle, pilot, event, payload, totals)
            for event, payload in output_events(f"live-{index}", index):
                chunk_seconds += await timed_event(handle, pilot, event, payload, chunk_totals)
                chunks += 1
            update_seconds += await timed_event(handle, pilot, *done, totals)
            if (index + 1) % TEXT_EVERY == 0:
                stream_text(app, handle, index)
                await pilot.pause()
        start = perf_counter()
        handle("run_completed", {"output_text": "Final answer."})
        await pilot.pause()
        run_end = perf_counter() - start
    updates = tools * len(tool_events("", 0))
    metrics = {
        "ms/update": update_seconds * 1000 / updates,
        "rebuilds/call": totals["rebuilds"] / tools,
        "relayouts/call": totals["relayouts"] / tools,
        "mounted-relayouts/call": totals["mounted-relayouts"] / tools,
        "layouts/call": totals["layouts"] / tools,
        "mounted/call": totals["mounted"] / tools,
        "removed/call": totals["removed"] / tools,
        "run-end ms": run_end * 1000,
    }
    if chunks:
        metrics["ms/output-chunk"] = chunk_seconds * 1000 / chunks
        metrics["relayouts/output-chunk"] = chunk_totals["relayouts"] / chunks
        metrics["mounted/output-chunk"] = chunk_totals["mounted"] / chunks
    return metrics


async def bench_live(tools: int, runs: int, *, raw: bool) -> None:
    await run_live_once(tools)
    print(f"tools={tools} history_turns={HISTORY_TURNS} streams_output={STREAMS_OUTPUT} (warm-up discarded)")
    samples: dict[str, list[float]] = {name: [] for name in LIVE_METRICS}
    for _ in range(runs):
        for name, value in (await run_live_once(tools)).items():
            samples[name].append(value)
    for name in LIVE_METRICS:
        values = samples[name]
        if not values:
            print(f"tools={tools:<4} {name:<22} n/a")
            continue
        print(
            f"tools={tools:<4} {name:<22} median={statistics.median(values):8.2f}"
            f"  min={min(values):8.2f}  max={max(values):8.2f}  n={len(values)}"
        )
        if raw:
            print(f"raw tools={tools} {name} " + " ".join(f"{value:.3f}" for value in values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, action="append", help="tool rows (repeatable); default 50 and 200")
    parser.add_argument("--group", type=int, default=10, help="tool rows per Explored group")
    parser.add_argument("--runs", type=int, default=7, help="timed runs after the warm-up")
    parser.add_argument("--raw", action="store_true", help="also print every sample")
    parser.add_argument("--live", action="store_true", help="measure a streamed live turn instead")
    parser.add_argument(
        "--tools", type=int, action="append", help="live-turn tool calls (repeatable); default 10 and 50"
    )
    args = parser.parse_args()
    print(f"checkout src: {CHECKOUT_SRC}")
    if args.live:
        count_render_work()
        for tools in args.tools or (10, 50):
            asyncio.run(bench_live(tools, args.runs, raw=args.raw))
        return
    for rows in args.rows or (50, 200):
        asyncio.run(bench(rows, args.group, args.runs, raw=args.raw))


if __name__ == "__main__":
    main()
