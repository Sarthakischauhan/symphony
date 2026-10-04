"""Session provenance is isolated from shared global knowledge in the memory UI."""
import asyncio

from textual.app import App
from textual.widgets import TabbedContent, Static

from coding_agent.learning.store import LearningStore
from coding_agent.tui.commands.catalog import SLASH_COMMANDS
from coding_agent.tui.screens.learning import LearningModal


def seed(store, session, text):
    job = store.enqueue_capture("test", [{"role": "user", "content": text}], session)
    store.complete_job(job, [{"text": text, "topic": "testing"}])
    store.consolidate()


def test_scoped_views_and_duplicate_fact_provenance(tmp_path):
    store = LearningStore(tmp_path, session_id="first")
    seed(store, "first", "First session tests require fixtures")
    seed(store, "second", "Second session tests require isolation")
    seed(store, "second", "First session tests require fixtures")
    store.memory_operation("add", target="user", text="Prefer concise responses")
    first = store.scoped_markdown("session", session_id="first")
    second = store.scoped_markdown("session", session_id="second")
    global_view = store.scoped_markdown("global")
    assert "fixtures" in first and "isolation" not in first and "concise" not in first
    assert "fixtures" in second and "isolation" in second
    assert "concise" in global_view and "fixtures" not in global_view
    assert "fixtures" not in store.scoped_markdown("session", session_id="missing")
    assert not {"flush", "dream"} & {item.name for item in SLASH_COMMANDS}


def test_memory_modal_tabs_switch_and_close(tmp_path):
    async def run():
        store = LearningStore(tmp_path, session_id="first")
        seed(store, "first", "First session tests require fixtures")
        store.memory_operation("add", target="user", text="Prefer concise responses")
        async with App().run_test() as pilot:
            modal = LearningModal(tmp_path, session_id="first", store=store)
            pilot.app.push_screen(modal)
            await pilot.pause()
            tabs = modal.query_one("#learning-tabs", TabbedContent)
            assert tabs.active == "memory-session"
            assert "fixtures" in str(modal.query_one("#session-memory-content", Static).render())
            assert "concise" in str(modal.query_one("#global-memory-content", Static).render())
            tabs.active = "memory-global"
            await pilot.pause()
            assert tabs.active == "memory-global"
            await pilot.press("escape")
            await pilot.pause()
            assert not modal.is_current
    asyncio.run(run())
