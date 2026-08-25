"""Nested-session UI for spawned child agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from rich.console import Group
from rich.text import Text
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.widgets import ToolCallWidget
from coding_agent.utils.text import clip_text, compact_json, preview_text


@dataclass
class SubagentRecord:
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
            args = payload.get("arguments") or {}
            self.tools.append({"name": str(payload.get("tool_name") or "tool"), "status": "running", "summary": compact_json(args) if args else "", "result": ""})
        elif event_type == "tool_execution_completed" and self.tools:
            self.tools[-1].update(status="done", result=preview_text(payload.get("result") or "", limit=180))
        elif event_type == "text_delta":
            self.output_text += str(payload.get("delta") or "")
        elif event_type in {"run_completed", "agent_completed"}:
            self.status = "completed"
            if payload.get("output_text"):
                self.output_text = str(payload["output_text"])
        elif event_type in {"run_failed", "run_cancelled", "agent_failed"}:
            self.status = "failed"
            if payload.get("message"):
                self.output_text = str(payload["message"])


class SubagentScreen(ModalBase[None]):
    CSS = """
    SubagentScreen { align: center middle; background: rgba(6, 14, 16, 0.78); }
    #subagent-pane { width: 94%; height: 92%; layout: vertical; background: #0b1012; border: round #245754; padding: 1 2; }
    #subagent-header, #subagent-footer { width: 100%; height: auto; padding: 1; background: #10201f; }
    #subagent-body { width: 100%; height: 1fr; padding: 1; }
    """

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
        r = self.record
        self.query_one("#subagent-header", Static).update(Text(f"SUBAGENT  {r.label or 'subagent'} · {r.status}\n{r.parent_id or '—'} → {r.agent_id or '—'}", style="#d7ecea"))
        body = Group(Text(f"TASK\n{clip_text(r.prompt, 600)}", style="#c8d8d6"), Text("\nOUTPUT\n" + (r.output_text or "Waiting for the child agent…"), style="#e8e8e8"))
        self.query_one("#subagent-log", Static).update(body)
        self.query_one("#subagent-footer", Static).update("live · Esc close" if r.status == "running" else "Esc close")


class SubagentWidget(ToolCallWidget):
    def __init__(self, call_id: str, tool_name: str) -> None:
        self.record: Optional[SubagentRecord] = None
        super().__init__(call_id, tool_name)
        self.add_class("subagent-call")

    def _tool_title(self) -> tuple[str, str]:
        return ("Subagent", "↳")

    def _summary(self) -> str:
        return (self.record.label if self.record else str(self.arguments.get("label") or self.arguments.get("prompt") or self.raw_arguments))

    def bind(self, record: SubagentRecord) -> None:
        self.record = record
        self.refresh_content()

    def open_screen(self) -> bool:
        record = self.record or SubagentRecord("", "", str(self.arguments.get("label") or "subagent"), str(self.arguments.get("prompt") or ""))
        self.record = record
        self.app.push_screen(SubagentScreen(record))
        return True

