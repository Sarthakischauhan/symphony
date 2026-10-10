"""Thinking and Thought blocks render markdown instead of raw markers."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from rich.console import Console, RenderableType
from rich.segment import Segment
from rich.style import Style

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.tools import ToolCallSummary
from coding_agent.tui.tools.snapshots import ThoughtSnapshot, ToolCallSnapshot
from coding_agent.tui.transcript import ReasoningWidget, UserMessage
from coding_agent.tui.transcript.process import ReasoningBody
from coding_agent.tui.transcript.thinking_markdown import (
    close_dangling_markers,
    render_thinking,
    thinking_plain_text,
)

SIZE = (100, 30)
THOUGHT = (
    "**Tracing the retry path**\n\n"
    "The *loader* wraps `read()` in a retry helper.\n\n"
    "- check the helper\n"
    "- check the caller\n\n"
    "## Next step"
)
RAW_MARKERS = ("**", "`", "*", "##")


def _app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CodingAgentApp:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return CodingAgentApp(workspace=tmp_path)


def _segments(renderable: RenderableType, width: int = 100) -> list[Segment]:
    console = Console(width=width, file=io.StringIO(), color_system=None)
    return [segment for segment in console.render(renderable) if segment.text.strip()]


def _plain(renderable: RenderableType, width: int = 100) -> str:
    console = Console(width=width, file=io.StringIO(), color_system=None)
    console.print(renderable)
    return "\n".join(line.rstrip() for line in console.file.getvalue().splitlines()).strip()


def _style_of(segments: list[Segment], fragment: str) -> Style:
    return next(segment.style or Style() for segment in segments if fragment in segment.text)


def test_completed_thought_renders_bold_italic_code_and_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            app.mount_transcript(UserMessage("why does it retry twice?"))
            app.set_reasoning(THOUGHT, new=True)
            app.finish_reasoning()
            await pilot.pause()

            body = app.query_one(ReasoningWidget).query_one(ReasoningBody)
            rendered = body.render()
            plain = _plain(rendered)
            for marker in RAW_MARKERS:
                assert marker not in plain
            assert "Tracing the retry path" in plain
            assert "• check the helper" in plain
            assert "• check the caller" in plain
            assert "Next step" in plain

            segments = _segments(rendered)
            assert _style_of(segments, "Tracing the retry path").bold
            assert _style_of(segments, "loader").italic
            assert _style_of(segments, "Next step").bold
            # Emphasis only: the prose keeps the widget's muted CSS colour.
            assert _style_of(segments, "Tracing the retry path").color is None
            assert _style_of(segments, "loader").color is None
            code = _style_of(segments, "read()")
            themed = body.get_component_rich_style("reasoning-text--code", partial=True)
            assert themed.color is not None and themed.bgcolor is not None
            assert code.color == themed.color
            assert code.bgcolor == themed.bgcolor

    asyncio.run(_run())


def test_thought_preview_rows_in_a_group_strip_markers() -> None:
    thought = ThoughtSnapshot(title="**Checking** the caller", content=THOUGHT)
    read = ToolCallSnapshot("read-0", label="Read", detail="src/loader.py")
    collapsed = ToolCallSummary((thought, read)).render().plain
    expanded = ToolCallSummary((thought, read), expanded=True).render().plain

    for preview in (collapsed, expanded):
        assert "**" not in preview
        assert "`" not in preview
        assert "*" not in preview
        assert "Tracing the retry path · The loader wraps read() in a retry helper." in preview
    assert "├ Checking the caller" in expanded
    # The preview stays one compact line per thought.
    assert len(collapsed.splitlines()) == 2


def test_markdown_links_keep_their_target() -> None:
    from markdown_it.tree import SyntaxTreeNode
    from rich.style import Style
    from rich.text import Text

    from coding_agent.tui.transcript.thinking_markdown import PARSER, append_inline

    text = Text()
    root = SyntaxTreeNode(PARSER.parse("[docs](https://example.com/docs) and plain"))
    inline = root.children[0].children[0]
    for child in inline.children:
        append_inline(text, child, Style(), Style())
    spans = [span for span in text.spans if span.style and span.style.link]
    assert spans
    assert spans[0].style.link == "https://example.com/docs"


def test_plain_text_separates_blocks_but_not_inline_spans() -> None:
    source = "# Plan\n\nfoo**bar** and `x`\nnext\n\n- one\n- *two*\n\n---\n\n```\ncode\n```"
    assert thinking_plain_text(source) == "Plan · foobar and x next · one · two · code"


@pytest.mark.parametrize(
    ("partial", "shown"),
    [
        ("**Tracing the re", "**Tracing the re**"),
        ("The *loader", "The *loader*"),
        ("calls `read(", "calls `read(`"),
        ("**bold *both", "**bold *both***"),
        ("ends with **", "ends with"),
        ("done **x** and `", "done **x** and"),
        ("a * b", "a * b"),
        ("* list item", "* list item"),
        ("```py\nprint(**kwargs", "```py\nprint(**kwargs"),
    ],
)
def test_streaming_closes_dangling_markers_for_display(partial: str, shown: str) -> None:
    assert close_dangling_markers(partial) == shown


def test_unclosed_bold_mid_stream_renders_and_corrects_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            app.mount_transcript(UserMessage("why does it retry twice?"))
            app.set_reasoning("**Tracing the re", new=True)
            await pilot.pause()
            thought = app.query_one(ReasoningWidget)
            body = thought.query_one(ReasoningBody)
            plain = _plain(body.render())
            assert plain == "Tracing the re"
            assert _style_of(_segments(body.render()), "Tracing the re").bold
            assert body.size.height == 1

            app.set_reasoning("**Tracing the retry path** with `read(", new=False)
            await pilot.pause()
            assert _plain(body.render()) == "Tracing the retry path with read("
            assert body.size.height == 1

            app.set_reasoning(THOUGHT, new=False)
            await pilot.pause()
            plain = _plain(body.render())
            assert "**" not in plain and "`" not in plain
            # Heading, blank, prose, blank, two items, blank, heading.
            assert body.size.height == len(plain.splitlines()) == 8

    asyncio.run(_run())


def test_unclosed_markers_never_raise_at_any_cut() -> None:
    source = THOUGHT + "\n\n```py\nx = 1\n```\n\n> quoted **text** and *more*"
    for end in range(len(source) + 1):
        rendered = render_thinking(source[:end], code_style=Style(), streaming=True)
        assert len(_plain(rendered, width=60).splitlines()) <= source[:end].count("\n") * 2 + 2


def test_thought_body_updates_in_place_across_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            app.mount_transcript(UserMessage("why does it retry twice?"))
            app.set_reasoning(THOUGHT[:1], new=True)
            await pilot.pause()
            thought = app.query_one(ReasoningWidget)
            body = thought.query_one(ReasoningBody)
            children = list(thought.walk_children())

            for end in range(2, len(THOUGHT) + 1, 3):
                app.set_reasoning(THOUGHT[:end], new=False)
                await pilot.pause()
                assert app.query_one(ReasoningWidget) is thought
                assert thought.query_one(ReasoningBody) is body
                assert list(thought.walk_children()) == children

            app.finish_reasoning()
            await pilot.pause()
            assert app.query_one(ReasoningWidget) is thought
            assert thought.query_one(ReasoningBody) is body
            assert list(thought.walk_children()) == children
            assert "**" not in _plain(body.render())

    asyncio.run(_run())
