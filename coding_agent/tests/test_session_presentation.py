"""Read-only archive reports include images, compactions, and complete history."""

import asyncio
import base64
from types import SimpleNamespace

from core_ai.types import Message
from core_harness.context import COMPACTED_CONTEXT_MARK
from textual.app import App

from coding_agent.learning import LearningStore
from coding_agent.persistence import JsonlPersistence
from coding_agent.persistence.presentation import session_images, session_report
from coding_agent.tui.commands.manager import SessionModal


def test_archive_report_and_image_gallery_survive_compaction(tmp_path):
    async def run():
        store = JsonlPersistence(tmp_path / "sessions")
        image = {"type": "image", "media_type": "image/png", "filename": "shot.png",
                 "data": base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode()}
        history = [Message(role="system", content="policy"),
                   Message(role="user", content=[{"type": "text", "text": "original question"}, image]),
                   Message(role="assistant", content="original response")]
        await store.save_conversation(session_id="s", messages=history)
        await store.append_event(event_type="tool_execution_completed", payload={
            "session_id": "s", "result": "complete tool output", "tool_name": "read_file"})
        await store.save_conversation(session_id="s", messages=[history[0], Message(
            role="user", content=COMPACTED_CONTEXT_MARK + "\narchived summary")])
        memory = LearningStore(tmp_path, session_dir=store.session_dir("s"))
        memory.memory_operation("add", text="Use focused tests")
        report = await session_report(SimpleNamespace(session_id="s", persistence=store))
        assert "original question" in report
        assert "original response" in report
        assert "archived summary" in report
        assert "complete tool output" in report
        assert "Use focused tests" in report
        assert "Archived images: 1" in report
        assert len(session_images(store.session_dir("s"))) == 1
        assert image["data"] not in report

        class TestApp(App):
            pass

        async with TestApp().run_test() as pilot:
            modal = SessionModal(report, store.session_dir("s"))
            pilot.app.push_screen(modal)
            await pilot.pause()
            assert modal.is_current
            await pilot.press("escape")
            await pilot.pause()
            assert not modal.is_current

    asyncio.run(run())


def test_non_file_backend_reports_unsupported():
    report = asyncio.run(session_report(SimpleNamespace(session_id="s", persistence=object())))
    assert "unavailable" in report
