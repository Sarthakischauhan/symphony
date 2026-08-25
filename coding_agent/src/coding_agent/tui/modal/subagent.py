"""Nested session screen for a spawned child agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Group
from rich.text import Text
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.modal.base import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.styles.modal import SUBAGENT_SCREEN_CSS
from coding_agent.utils.text import clip_text, compact_json, preview_text


@dataclass
class SubagentRecord:
    """Live transcript of one child agent, keyed by agent_id."""

    agent_id: str
    parent_id: str
    label: str
    prompt: str
    status: str = "running"
    model_id: str = ""
    output_text: str = ""
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)

    def ingest(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))
        if event_type == "run_started":
            self.model_id = str(payload.get("model_id") or self.model_id)
        elif event_type == "tool_execution_started":
            arguments = payload.get("arguments") or {}
            self.tools.append(
                {
                    "name": str(payload.get("tool_name") or "tool"),
                    "status": "running",
                    "summary": compact_json(arguments) if arguments else "",
                    "result": "",
                }
            )
        elif event_type == "tool_execution_completed":
            if self.tools:
                self.tools[-1]["status"] = "done"
                self.tools[-1]["result"] = preview_text(payload.get("result") or "", limit=180)
        elif event_type == "text_delta":
            self.output_text += str(payload.get("delta") or "")
        elif event_type in {"run_completed", "agent_completed"}:
            self.status = "completed"
            output = payload.get("output_text")
            if output:
                self.output_text = str(output)
        elif event_type in {"run_failed", "run_cancelled", "agent_failed"}:
            self.status = "failed"
            message = payload.get("message")
            if message:
                self.output_text = str(message)


def _short_id(value: str) -> str:
    return value.replace("-", "")[:8] if value else "—"


class SubagentScreen(ModalBase[None]):
    """Full nested-session overlay for one child agent — not a content modal."""

    CSS = SUBAGENT_SCREEN_CSS

    def __init__(self, record: SubagentRecord) -> None:
        super().__init__()
        self.record = record

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="subagent-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static(id="subagent-header")
            with ModalScroll(id="subagent-body"):
                yield Static(id="subagent-log")
            yield Static(id="subagent-footer")

    def on_mount(self) -> None:
        self.refresh_record()

    def refresh_record(self) -> None:
        record = self.record
        label = record.label.strip() or "subagent"
        status = {
            "running": "running",
            "completed": "done",
            "failed": "failed",
        }.get(record.status, record.status)
        header = Text()
        header.append("SUBAGENT", style="bold #8fd4cf")
        header.append(f"  {label}  ·  {status}\n", style="#d7ecea")
        header.append(
            f"{_short_id(record.parent_id)}  →  {_short_id(record.agent_id)}",
            style="#6f8f8c",
        )
        if record.model_id:
            header.append(f"  ·  {record.model_id}", style="#6f8f8c")
        self.query_one("#subagent-header", Static).update(header)
        self.query_one("#subagent-log", Static).update(self._body())
        footer = (
            "live  ·  Esc close"
            if record.status == "running"
            else "Esc close"
        )
        self.query_one("#subagent-footer", Static).update(footer)

    def _body(self) -> Group:
        record = self.record
        rows: list[Any] = []
        if record.prompt:
            prompt = Text()
            prompt.append("TASK\n", style="bold #6f8f8c")
            prompt.append(clip_text(record.prompt, 600), style="#c8d8d6")
            rows.append(prompt)
        if record.tools:
            tools = Text()
            tools.append("\nTOOLS\n", style="bold #6f8f8c")
            for tool in record.tools:
                marker = "●" if tool["status"] == "running" else "✓"
                tools.append(f"{marker}  {tool['name']}", style="#8fd4cf")
                if tool.get("summary"):
                    tools.append(f"  {clip_text(str(tool['summary']), 80)}", style="#7a7a7a")
                tools.append("\n")
                if tool.get("result"):
                    tools.append(f"   {clip_text(str(tool['result']), 160)}\n", style="#8a8a8a")
            rows.append(tools)
        output = Text()
        output.append("\nOUTPUT\n", style="bold #6f8f8c")
        if record.output_text.strip():
            output.append(record.output_text.strip(), style="#e8e8e8")
        elif record.status == "running":
            output.append("Waiting for the child agent…", style="#6f8f8c")
        else:
            output.append("No output.", style="#6f8f8c")
        rows.append(output)
        return Group(*rows)
