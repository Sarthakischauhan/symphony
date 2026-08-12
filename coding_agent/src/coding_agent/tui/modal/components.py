"""Reusable presentation components for Symphony's detail modals."""

from __future__ import annotations

from datetime import datetime
from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from coding_agent.learning import Lesson
from coding_agent.tui.theme import themed_markdown


class ModalHeader(Static):
    """A compact product header with a quiet eyebrow and supporting detail."""

    def __init__(self, eyebrow: str, title: str, detail: str, **kwargs: object) -> None:
        super().__init__(
            f"{eyebrow.upper()}\n{title}\n{detail}",
            classes="modal-header",
            **kwargs,
        )


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
        heading = Text()
        heading.append(f"{index:02d}  ", style="bold #596b76")
        heading.append(lesson.summary, style="bold #d8d8d8")
        rows.append(heading)

        meta = Text("     ")
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
        rows.append(Text(f"\n     {label}", style=f"bold {color}"))
        for item in items:
            line = Text("     ")
            line.append(f"{marker}  ", style=color)
            line.append(item, style="#aaaaaa")
            rows.append(line)


class PlanSectionCard(Static):
    """A plan section presented as a numbered, readable card."""

    def __init__(self, title: str, body: str, index: int) -> None:
        heading = Text()
        heading.append(f"{index:02d}  ", style="bold #596b76")
        heading.append(title, style="bold #d8d8d8")
        super().__init__(
            Group(heading, themed_markdown(body or "_No details provided._")),
            classes="content-card plan-section-card",
        )
