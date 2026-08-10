#!/usr/bin/env python3
"""Capture a PNG screenshot of the coding agent TUI for the README."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.state import RunMetrics
from coding_agent.tui.widgets import UserMessage

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "tui-screenshot.png"
WORKSPACE = Path("/workspace/demo-app")
MODEL = "openai:gpt-4.1"

PATCH_ARGS = {
    "path": "src/api/routes.py",
    "old_str": (
        '@router.get("/ready")\n'
        "def ready() -> dict[str, str]:\n"
        '    return {"status": "ready"}\n'
    ),
    "new_str": (
        '@router.get("/ready")\n'
        "def ready() -> dict[str, str]:\n"
        '    return {"status": "ready"}\n'
        "\n"
        '@router.get("/health")\n'
        "def health() -> dict[str, str]:\n"
        '    return {"status": "ok"}\n'
    ),
}


def _fake_build_agent(**_kwargs):
    return SimpleNamespace(
        harness=SimpleNamespace(model_id=MODEL),
        set_mode=lambda _mode: None,
    )


def _svg_to_png(svg_text: str, dest: Path, *, width: int = 1800) -> None:
    """Rasterize Textual SVG with a system mono font that has box-drawing glyphs."""
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "cairosvg is required to write PNG screenshots. "
            "Install with: uv pip install cairosvg"
        ) from exc

    # Remote Fira Code often lacks the TUI line glyphs in headless renders.
    svg_text = re.sub(r"@font-face\s*\{.*?\}", "", svg_text, flags=re.S)
    svg_text = svg_text.replace(
        "font-family: Fira Code, monospace",
        'font-family: "DejaVu Sans Mono", monospace',
    )
    svg_text = svg_text.replace(
        'font-family: "Fira Code"',
        'font-family: "DejaVu Sans Mono"',
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(dest), output_width=width)


async def _populate(app: CodingAgentApp) -> None:
    for notice in list(app.query(".notice")):
        notice.remove()

    app._mount_transcript(
        UserMessage("Add a health check endpoint and a short README note.")
    )

    app.set_thinking("Explored the API surface")
    app.set_reasoning(
        "Find the existing FastAPI routes, add `/health`, then document it.",
        new=True,
    )

    app.add_tool("call_search", "search")
    app.update_tool(
        "call_search",
        arguments={"query": "FastAPI", "path": "src"},
        status="running",
    )
    app.update_tool(
        "call_search",
        arguments={"query": "FastAPI", "path": "src"},
        status="done",
        result="src/api/main.py\nsrc/api/routes.py",
    )

    app.add_tool("call_read", "read_file")
    app.update_tool(
        "call_read",
        arguments={"path": "src/api/routes.py", "offset": 1, "limit": 40},
        status="running",
    )
    app.update_tool(
        "call_read",
        arguments={"path": "src/api/routes.py", "offset": 1, "limit": 40},
        status="done",
        result="\n".join(f"line {i}" for i in range(1, 41)),
    )

    app.add_tool("call_patch", "patch")
    app.update_tool("call_patch", arguments=PATCH_ARGS, status="running")
    app.update_tool(
        "call_patch",
        arguments=PATCH_ARGS,
        status="done",
        result="patched 1 occurrence",
    )

    app.finish_process("Used 3 tools · 1 edit", collapse=False)
    app.set_assistant(
        "Added `GET /health` in `src/api/routes.py` and noted it in the README.\n\n"
        "```python\n"
        '@router.get("/health")\n'
        "def health() -> dict[str, str]:\n"
        '    return {"status": "ok"}\n'
        "```\n\n"
        "Want me to add a test for it next?",
        new=True,
    )

    app._ui_state.phase = "idle"
    app._ui_state.model_id = MODEL
    app._ui_state.detail = "ready"
    app._ui_state.metrics = RunMetrics(
        prompt_tokens=1840,
        completion_tokens=312,
        total_tokens=2152,
        cumulative_tokens=2152,
        context_limit=128000,
        context_left=125848,
        tokens_used=2152,
        utilization=0.017,
    )
    app.query_one("#topbar").set_context(WORKSPACE, MODEL)
    app._set_status("")
    app.query_one("#prompt").value = ""
    app.query_one("#composer-hint").update("BUILD · Tab mode · Enter to send")
    app.query_one("#transcript").scroll_home(animate=False)


async def main() -> None:
    os.environ.pop("OPENAI_API_KEY", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with patch("coding_agent.tui.app.build_agent", side_effect=_fake_build_agent):
        app = CodingAgentApp(workspace=WORKSPACE, model_id=MODEL)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            await _populate(app)
            await pilot.pause(0.1)
            svg_text = app.export_screenshot()
            _svg_to_png(svg_text, OUT)
            print(OUT)


if __name__ == "__main__":
    asyncio.run(main())
