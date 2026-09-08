"""Plan modal screen."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.plan import PlanStore
from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import PLAN_MODAL_CSS

def _numbered_plan(body: str) -> Text:
    """Render plan text with a stable line-number gutter like the diff view."""
    lines = (body or "_No details provided._").splitlines()
    width = max(2, len(str(len(lines))))
    rendered = Text(no_wrap=True, overflow="crop")
    for number, line in enumerate(lines, start=1):
        rendered.append(
            f"{number:>{width}} │ ",
            style="#687e8b",
        )
        rendered.append(line, style="#b8bec1")
        rendered.append("\n")
    if rendered.plain.endswith("\n"):
        rendered = rendered[:-1]
    return rendered


class PlanSectionCard(Container):
    """A plan section with a compact header and line-numbered body."""

    def __init__(self, title: str, body: str, index: int) -> None:
        self.title = title
        self.body = body
        self.index = index
        super().__init__(classes="plan-section-card")

    def compose(self):  # type: ignore[no-untyped-def]
        with Horizontal(classes="plan-section-header"):
            yield Static(f"{self.index:02}", classes="plan-section-number")
            yield Static(self.title, classes="plan-section-title")
        yield Static(_numbered_plan(self.body), classes="plan-section-body", markup=False)

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


class PlanActionButton(Static, can_focus=True):
    def __init__(self, label: str, action: str, **kwargs):
        super().__init__(label, **kwargs)
        self.action = action

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss(self.action)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.screen.dismiss(self.action)


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
            yield ModalCloseButton("Esc", id="modal-close")
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
                yield PlanActionButton("Build now", "build", id="plan-build")
                yield PlanActionButton("Request changes", "changes", id="plan-changes")
                yield PlanActionButton("Quit", "quit", id="plan-quit")
