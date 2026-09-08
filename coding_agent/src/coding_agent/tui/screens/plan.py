"""Plan modal screen."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from textual import events
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.plan import PlanStore
from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import PLAN_MODAL_CSS, themed_markdown

PlanAction = Literal["build", "changes", "quit"]


def _plan_document(markdown: str) -> tuple[str, str]:
    """Return a header title and the Markdown body, minus store chrome."""
    task = ""
    lines: list[str] = []
    for line in markdown.splitlines():
        task_match = re.match(r"\*\*Task:\*\*\s*(.+)", line)
        if task_match:
            task = task_match.group(1).strip()
            continue
        if re.fullmatch(r"#\s+Plan\s*", line, re.I):
            continue
        lines.append(line)
    body = "\n".join(lines).strip()
    if not task:
        heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
        if heading:
            task = heading.group(1).strip()
    return task or "Plan", body


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
    """Fullscreen modal showing the latest workspace plan as Markdown."""

    CSS = PLAN_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        store = PlanStore(self.workspace)
        title, body = _plan_document(store.to_markdown())
        with Container(id="plan-pane", classes="modal-pane"):
            with Horizontal(id="plan-header"):
                yield Static("plan", id="plan-kicker")
                yield Static(title, id="plan-title")
                yield ModalCloseButton("Esc", id="modal-close")
            with ModalScroll(id="plan-body", classes="modal-body"):
                if not body:
                    yield EmptyState(
                        "No plan available",
                        "Create a plan first, then return here to review and build it.",
                    )
                else:
                    yield Static(themed_markdown(body), id="plan-markdown")
            with Horizontal(id="plan-actions"):
                yield Static("↑↓ scroll   ·   Esc close", id="plan-hint")
                yield PlanActionButton("Build now", "build", id="plan-build")
                yield PlanActionButton("Request changes", "changes", id="plan-changes")
                yield PlanActionButton("Quit", "quit", id="plan-quit")
