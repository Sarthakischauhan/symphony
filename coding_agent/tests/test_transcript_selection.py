"""Mouse selection must both extract and visibly highlight Rich transcript text."""

import asyncio

from rich.console import Group
from rich.text import Text
from textual.app import App
from textual.containers import VerticalScroll

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.runtime.subagent import SubagentRecord, SubagentScreen
from coding_agent.tui.transcript.messages import AssistantMessage, SelectableStatic, UserMessage
from coding_agent.tui.transcript.surface import TranscriptSurface


def test_rich_transcript_mouse_drag_highlights_and_extracts():
    class SelectionApp(App):
        CSS = "Screen .screen--selection { background: #ff00ff; color: #ffffff; }"

        def compose(self):
            with VerticalScroll():
                yield AssistantMessage("Hello **world**\n\n```python\nprint('hello')\n```")

    async def run():
        app = SelectionApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            message = app.query_one(AssistantMessage)
            before = message.render_line(0)
            await pilot.mouse_down(message, offset=(0, 0))
            await pilot.hover(message, offset=(4, 0))
            await pilot.mouse_up(message, offset=(4, 0))
            await pilot.pause()
            assert app.screen.get_selected_text() == "Hello"
            after = message.render_line(0)
            assert list(after) != list(before), "Mouse selection must visibly highlight the Rich text"
            selected_segment = next(segment for segment in after if segment.text.startswith("Hello"))
            assert selected_segment.style.color == list(before)[0].style.color
            assert selected_segment.style.bgcolor is not None
            code_y = next(y for y in range(message.size.height) if "print" in message.render_line(y).text)
            code = message.render_line(code_y).text
            x = code.index("print")
            await pilot.mouse_down(message, offset=(x, code_y))
            await pilot.hover(message, offset=(x + 4, code_y))
            await pilot.mouse_up(message, offset=(x + 4, code_y))
            await pilot.pause()
            assert app.screen.get_selected_text() == "print"

    asyncio.run(run())


def test_rich_selection_unicode_updates_and_clear():
    class SelectionApp(App):
        def compose(self):
            yield SelectableStatic(Group(Text("界", style="bold"), Text("second")))

    async def run():
        app = SelectionApp()
        async with app.run_test(size=(40, 12)) as pilot:
            message = app.query_one(SelectableStatic)
            message.update(Group(Text.assemble(("界", "bold"), (" hello", "italic"))))
            await pilot.pause()
            original = list(message.render_line(0))
            await pilot.mouse_down(message, offset=(3, 0))
            await pilot.hover(message, offset=(7, 0))
            await pilot.mouse_up(message, offset=(7, 0))
            await pilot.pause()
            assert app.screen.get_selected_text() == "hello"
            assert list(message.render_line(0)) != original
            app.screen.clear_selection()
            await pilot.pause()
            assert list(message.render_line(0)) == original
            assert app.screen.get_selected_text() is None

    asyncio.run(run())


def test_mouse_release_copies_selection():
    class CopyApp(App, TranscriptSurface):
        def compose(self):
            yield SelectableStatic("copy me")

    async def run():
        app = CopyApp()
        async with app.run_test(size=(40, 8)) as pilot:
            message = app.query_one(SelectableStatic)
            await pilot.mouse_down(message, offset=(0, 0))
            await pilot.hover(message, offset=(3, 0))
            await pilot.mouse_up(message, offset=(3, 0))
            await pilot.pause()
            assert app.clipboard == "copy"
            assert app.screen.get_selected_text() is None
            assert [notification.message for notification in app._notifications] == [
                "Copied to clipboard!"
            ]

    asyncio.run(run())


def test_child_screen_mouse_release_copies_selection(tmp_path):
    """A drag-select in a pushed SubagentScreen copies through the app.

    ``copy_to_clipboard`` exists only on ``App``; the shared transcript surface
    must reach it through ``self.app`` when it is mixed into a ``Screen``.
    """
    record = SubagentRecord(
        agent_id="child", parent_id="parent", label="Inspector", prompt="copy me from the child"
    )

    async def run():
        app = CodingAgentApp(workspace=tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            app.open_subagent(record)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SubagentScreen)
            message = screen.query_one(UserMessage)
            await pilot.mouse_down(message, offset=(3, 0))
            await pilot.hover(message, offset=(6, 0))
            await pilot.mouse_up(message, offset=(6, 0))
            await pilot.pause()
            assert app.clipboard == "copy"
            assert screen.get_selected_text() is None
            assert [notification.message for notification in app._notifications] == [
                "Copied to clipboard!"
            ]
            assert app.screen is screen

    asyncio.run(run())


def test_child_screen_shows_artifacts_from_child_events(tmp_path):
    """Artifact events reach the shared surface with state the Screen owns."""
    record = SubagentRecord(agent_id="child", parent_id="parent", label="Inspector", prompt="write notes")
    entry = tmp_path / "artifacts" / "notes" / "v1" / "notes.md"

    async def run():
        app = CodingAgentApp(workspace=tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            app.open_subagent(record)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SubagentScreen)
            record.ingest("artifact_created", {
                "agent_id": "child", "parent_id": "parent", "path": str(entry),
                "title": "Notes", "kind": "markdown", "version": 1,
            })
            screen.refresh_record()
            await pilot.pause()
            assert [title for title, _detail, _path in screen._session_artifacts.values()] == ["Notes"]
            assert not app._session_artifacts

    asyncio.run(run())
