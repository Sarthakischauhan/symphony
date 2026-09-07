"""Learning modal screen."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.text import Text
from textual.containers import Container, Horizontal
from textual.widgets import Static

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
    """Fullscreen modal showing stored learnings as scannable cards."""

    CSS = LEARNING_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        store = LearningStore(self.workspace)
        memory = store.memory_path.read_text(encoding="utf-8") if store.memory_path.exists() else ""
        user = store.user_path.read_text(encoding="utf-8") if store.user_path.exists() else ""
        with Container(id="learning-pane", classes="modal-pane"):
            with Horizontal(id="learning-header"):
                yield Static("learning", id="learning-title")
                yield Static(
                    "durable memory",
                    id="learning-counter",
                )
                yield ModalCloseButton("esc  close", id="modal-close")
            with ModalScroll(id="learning-body", classes="modal-body"):
                yield Static("MEMORY.md", classes="learning-section")
                yield Static(memory or "(empty)", classes="learning-content")
                yield Static("USER.md", classes="learning-section")
                yield Static(user or "(empty)", classes="learning-content")
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="learning-hint",
                classes="modal-footer",
            )
