"""Modal view for the latest agent plan."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from textual import events
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static

from coding_agent.plan import PlanStore
from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.modal.components import EmptyState, PlanSectionCard
from coding_agent.tui.styles.plan import PLAN_MODAL_CSS


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
            with VerticalScroll(id="plan-body", classes="modal-body"):
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
