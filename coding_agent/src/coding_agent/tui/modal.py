"""Modal screens used by the Symphony TUI."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Generic, Literal, TypeVar

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from coding_agent.learning import LearningStore, Lesson
from coding_agent.plan import PlanStore
from coding_agent.tui.styles import (
    CONTENT_MODAL_CSS,
    DIFF_MODAL_CSS,
    LEARNING_MODAL_CSS,
    PLAN_MODAL_CSS,
)
from coding_agent.tui.theme import SYMPHONY_CODE_THEME, themed_markdown
from coding_agent.utils.diff import diff_stats, read_workspace_diff, split_diff

# --- base.py ---
ResultT = TypeVar("ResultT")


class ModalCloseButton(Static, can_focus=True):
    """Small top-right close control shared by all modal screens."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.screen.dismiss(None)


class ModalScroll(VerticalScroll):
    """Scrollable modal body that always reserves Escape for closing."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
    ]

    def action_close_modal(self) -> None:
        self.screen.dismiss(None)

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.screen.dismiss(None)
            return
        await super()._on_key(event)


class ModalBase(ModalScreen[ResultT], Generic[ResultT]):
    """Base modal with a consistent close button and Escape behavior."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
    ]

    def action_close_modal(self) -> None:
        self.dismiss(None)


class ContentModal(ModalBase[None]):
    """Modal used to inspect transcript content hidden behind a compact link."""

    CSS = CONTENT_MODAL_CSS

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield Static(self.content, id="content-text", markup=False)
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")

# --- components.py ---
class EmptyState(Static):
    """Friendly empty state shared by data-backed modal screens."""

    def __init__(self, title: str, detail: str, **kwargs: object) -> None:
        super().__init__(
            Group(
                Text("◇", style="bold #738794"),
                Text(title, style="bold #c8c8c8"),
                Text(detail, style="#6f6f6f"),
            ),
            classes="empty-state",
            **kwargs,
        )


def _human_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%b %d, %Y")


class LearningCard(Static):
    """Structured lesson card with context, outcomes, and confidence."""

    def __init__(self, lesson: Lesson, index: int) -> None:
        rows: list[object] = []
        meta = Text()
        confidence_color = "#79a985" if lesson.confidence >= 0.7 else "#d0a85c"
        meta.append(f"{round(lesson.confidence * 100)}% confidence", style=confidence_color)
        if lesson.created_at:
            meta.append(f"  ·  {_human_date(lesson.created_at)}", style="#686868")
        if lesson.source_task:
            meta.append(f"  ·  {lesson.source_task}", style="#777777")
        rows.append(meta)

        self._append_items(rows, "WHEN TO USE", lesson.applicable_when, "#8eafc2", "›")
        self._append_items(rows, "WORKED", lesson.worked, "#79a985", "+")
        self._append_items(rows, "WATCH OUT", lesson.failed, "#c67b82", "−")
        super().__init__(Group(*rows), classes="content-card learning-card")

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


class PlanSectionCard(Static):
    """A plan section presented as a numbered, readable card."""

    def __init__(self, title: str, body: str, index: int) -> None:
        super().__init__(
            Group(
                Text(f"{index:02}  {title}", style="#8f835a"),
                Text(""),
                themed_markdown(body or "_No details provided._"),
            ),
            classes="content-card plan-section-card",
        )

# --- diff.py ---
class DiffFileCard(Container):
    """One changed file with a clear header, stats, and highlighted patch."""

    def __init__(self, path: str, body: str) -> None:
        self.path = path
        self.body = body
        self.additions, self.deletions = diff_stats(body.splitlines())
        super().__init__(classes="diff-file-card")

    def compose(self):  # type: ignore[no-untyped-def]
        stats = Text()
        stats.append(f"+{self.additions}", style="bold #8fc49a")
        stats.append(f"  −{self.deletions}", style="bold #df8b91")
        with Horizontal(classes="diff-file-header"):
            yield Static(Text(self.path, style="bold #d0d0d0"), classes="diff-file-path")
            yield Static(stats, classes="diff-file-stats")
        yield Static(
            Syntax(
                self.body,
                "diff",
                theme=SYMPHONY_CODE_THEME,  # type: ignore[arg-type]
                line_numbers=False,
                word_wrap=False,
            ),
            classes="diff-patch",
        )


class DiffModal(ModalBase[None]):
    """Fullscreen modal for inspecting the current git diff."""

    CSS = DIFF_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        files = split_diff(diff_text)
        with Container(id="diff-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            with ModalScroll(id="diff-body", classes="modal-body"):
                if not files:
                    is_clean = diff_text.strip() in {"", "No local changes found."}
                    yield EmptyState(
                        "Working tree is clean" if is_clean else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                for path, body in files:
                    yield DiffFileCard(path, body)
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="diff-hint",
                classes="modal-footer",
            )

# --- learning.py ---
class LearningModal(ModalBase[None]):
    """Fullscreen modal showing stored learnings as scannable cards."""

    CSS = LEARNING_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        lessons = list(reversed(LearningStore(self.workspace).load()))
        with Container(id="learning-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            with ModalScroll(id="learning-body", classes="modal-body"):
                if not lessons:
                    yield EmptyState(
                        "No learnings yet",
                        "Lessons from successful agent runs will collect here.",
                    )
                for index, lesson in enumerate(lessons, start=1):
                    yield LearningCard(lesson, index)
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="learning-hint",
                classes="modal-footer",
            )

# --- plan.py ---
PlanAction = Literal["build"]


def _plan_sections(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract the task and top-level sections from a generated Markdown plan."""
    task = ""
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    for line in markdown.splitlines():
        task_match = re.match(r"\*\*Task:\*\*\s*(.+)", line)
        if task_match:
            task = task_match.group(1).strip()
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            if any(item.strip() for item in current_lines):
                sections.append((current_title, current_lines))
            current_title = heading.group(1).strip()
            current_lines = []
            continue
        if line.strip() == "# Plan":
            continue
        if line.startswith("# "):
            current_lines.append(f"**{line.removeprefix('# ').strip()}**")
            continue
        current_lines.append(line)
    if any(item.strip() for item in current_lines):
        sections.append((current_title, current_lines))
    return task, [(title, "\n".join(lines).strip()) for title, lines in sections]


class PlanBuildAction(Static, can_focus=True):
    """Compact text action used in the plan status bar."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss("build")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.screen.dismiss("build")


class PlanModal(ModalBase[PlanAction | None]):
    """Fullscreen modal showing the latest workspace plan."""

    CSS = PLAN_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        store = PlanStore(self.workspace)
        markdown = store.to_markdown()
        _task, sections = _plan_sections(markdown)
        with Container(id="plan-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            with ModalScroll(id="plan-body", classes="modal-body"):
                if not sections:
                    yield EmptyState(
                        "No plan available",
                        "Create a plan first, then return here to review and build it.",
                    )
                for index, (title, body) in enumerate(sections, start=1):
                    yield PlanSectionCard(title, body, index)
            with Horizontal(id="plan-actions"):
                yield Static("↑↓ scroll   ·   Esc close", id="plan-hint")
                yield PlanBuildAction("Build now  →", id="plan-build")

__all__ = [
    "ContentModal",
    "DiffFileCard",
    "DiffModal",
    "EmptyState",
    "LearningCard",
    "LearningModal",
    "ModalBase",
    "ModalCloseButton",
    "ModalScroll",
    "PlanBuildAction",
    "PlanModal",
    "PlanSectionCard",
]


def __getattr__(name: str):
    if name == "ImageModal":
        from coding_agent.tui.images import ImageModal
        return ImageModal
    raise AttributeError(name)
