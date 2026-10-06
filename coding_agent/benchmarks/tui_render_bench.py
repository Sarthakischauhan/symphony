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

Animations are off (``TEXTUAL_ANIMATIONS=none``) so row fade-ins do not count.
The first run is a warm-up and is discarded. Times are in milliseconds.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

CHECKOUT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(CHECKOUT_SRC))
os.environ.pop("OPENAI_API_KEY", None)
os.environ["HOME"] = tempfile.mkdtemp(prefix="tui-bench-home-")
# Fade/settle animations would otherwise put their 0.12-0.18 s durations into
# the timings; with animations off Textual finishes them immediately.
os.environ["TEXTUAL_ANIMATIONS"] = "none"

from textual.containers import VerticalScroll  # noqa: E402

from coding_agent.tui.app import CodingAgentApp  # noqa: E402
from coding_agent.tui.tools.snapshots import ToolCallSummary  # noqa: E402

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, action="append", help="tool rows (repeatable); default 50 and 200")
    parser.add_argument("--group", type=int, default=10, help="tool rows per Explored group")
    parser.add_argument("--runs", type=int, default=7, help="timed runs after the warm-up")
    parser.add_argument("--raw", action="store_true", help="also print every sample")
    args = parser.parse_args()
    print(f"checkout src: {CHECKOUT_SRC}")
    for rows in args.rows or (50, 200):
        asyncio.run(bench(rows, args.group, args.runs, raw=args.raw))


if __name__ == "__main__":
    main()
