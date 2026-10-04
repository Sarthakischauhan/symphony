"""Learning modal screen."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.text import Text
from textual.containers import Container, Horizontal
from textual.widgets import Static, TabbedContent, TabPane

from coding_agent.learning import LearningStore, Lesson
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import LEARNING_MODAL_CSS

def _human_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%b %d, %Y")


class LearningCard(Container):
    """A diff-modal-style lesson row with a compact header and body."""

    def __init__(self, lesson: Lesson, index: int) -> None:
        self.lesson = lesson
        self.index = index
        super().__init__(classes="learning-card")

    def compose(self):  # type: ignore[no-untyped-def]
        lesson = self.lesson
        confidence_color = "#79a985" if lesson.confidence >= 0.7 else "#d0a85c"
        meta = Text()
        meta.append(f"{round(lesson.confidence * 100)}%", style=f"bold {confidence_color}")
        if lesson.created_at:
            meta.append(f"  {_human_date(lesson.created_at)}", style="#858d91")
        if lesson.source_task:
            meta.append(f"  ·  {lesson.source_task}", style="#858d91")
        with Horizontal(classes="learning-card-header"):
            yield Static("◆", classes="learning-marker")
            yield Static(f"lesson {self.index}", classes="learning-card-title")
            yield Static(meta, classes="learning-meta")
        rows: list[object] = []
        self._append_items(rows, "WHEN TO USE", lesson.applicable_when, "#8eafc2", "›")
        self._append_items(rows, "WORKED", lesson.worked, "#79a985", "+")
        self._append_items(rows, "WATCH OUT", lesson.failed, "#c67b82", "−")
        yield Static(Group(*rows), classes="learning-body-content")

    @staticmethod
    def _append_items(
        rows: list[object], label: str, items: list[str], color: str, marker: str
    ) -> None:
        if not items:
            return
        rows.append(Text(f"\n{label}", style=color))
        for item in items:
            line = Text("  ")
            line.append(f"{marker}  ", style=color)
            line.append(item, style="#aaaaaa")
            rows.append(line)


# --- learning.py ---
class LearningModal(ModalBase[None]):
    """Memory inspector separating current-session provenance from global facts."""

    CSS = LEARNING_MODAL_CSS

    def __init__(
        self,
        workspace: Path,
        *,
        session_id: str | None = None,
        store: LearningStore | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.session_id = session_id
        self.store = store

    def compose(self):  # type: ignore[no-untyped-def]
        store = self.store or LearningStore(self.workspace, session_id=self.session_id)
        session = self.session_id or store.session_id
        self.store = store
        with Container(id="learning-pane", classes="modal-pane"):
            with Horizontal(id="learning-header"):
                yield Static("learning", id="learning-title")
                yield Static(
                    f"session {session[:8]}" if session else "no active session",
                    id="learning-counter",
                )
                yield ModalCloseButton("esc  close", id="modal-close")
            with TabbedContent(initial="memory-session", id="learning-tabs"):
                with TabPane("Session", id="memory-session"):
                    with ModalScroll(id="session-memory-body", classes="modal-body"):
                        yield Static(
                            store.scoped_markdown("session", session_id=session),
                            id="session-memory-content", classes="learning-content", markup=False,
                        )
                with TabPane("Global", id="memory-global"):
                    with ModalScroll(id="global-memory-body", classes="modal-body"):
                        yield Static(
                            store.scoped_markdown("global"),
                            id="global-memory-content", classes="learning-content", markup=False,
                        )
            yield Static(
                "click tabs to switch   ·   ↑↓ scroll   ·   Esc close",
                id="learning-hint",
                classes="modal-footer",
            )
