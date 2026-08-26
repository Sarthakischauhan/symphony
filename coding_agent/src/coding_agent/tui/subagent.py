"""Nested transcript UI for spawned child agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from coding_agent.tui.modal import ModalBase
from coding_agent.tui.styles import APP_CSS
from coding_agent.tui.widgets import (
    AssistantMessage,
    BashToolHeader,
    RunProcess,
    ThinkingStatus,
    ToolCallWidget,
    TopBar,
    UserMessage,
    make_tool_widget,
)
from coding_agent.utils.text import clip_text, compact_json, preview_text


@dataclass
class SubagentRecord:
    """Live child-agent transcript, keyed by ``agent_id``."""

    agent_id: str
    parent_id: str
    label: str
    prompt: str
    status: str = "running"
    model_id: str = ""
    output_text: str = ""
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)

    def _tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        call_id = str(payload.get("tool_call_id") or f"tool-{len(self.tools)}")
        existing = next(
            (tool for tool in self.tools if tool.get("id") == call_id),
            None,
        )
        if existing is not None:
            return existing
        tool = {
            "id": call_id,
            "name": str(payload.get("tool_name") or "tool"),
            "status": "preparing",
            "arguments": {},
            "raw_arguments": "",
            "summary": "",
            "result": "",
        }
        self.tools.append(tool)
        return tool

    def ingest(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))
        if event_type == "run_started":
            self.model_id = str(payload.get("model_id") or self.model_id)
        elif event_type == "tool_call_started":
            tool = self._tool(payload)
            tool["name"] = str(payload.get("tool_name") or tool["name"])
        elif event_type == "tool_call_delta":
            tool = self._tool(payload)
            raw = str(tool.get("raw_arguments") or "") + str(payload.get("delta") or "")
            tool["raw_arguments"] = raw
            tool["summary"] = raw
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = None
            if isinstance(arguments, dict):
                tool["arguments"] = arguments
                tool["summary"] = compact_json(arguments)
        elif event_type == "tool_execution_started":
            tool = self._tool(payload)
            arguments = payload.get("arguments") or {}
            tool.update(
                name=str(payload.get("tool_name") or tool["name"]),
                status="running",
                arguments=arguments,
                summary=compact_json(arguments) if arguments else tool["summary"],
            )
        elif event_type == "tool_execution_completed":
            tool = self._tool(payload)
            result = payload.get("result") or ""
            tool.update(
                name=str(payload.get("tool_name") or tool["name"]),
                status=(
                    "failed" if str(payload.get("status") or "") == "error" else "done"
                ),
                result=preview_text(result, limit=400),
            )
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
    """Full-screen child transcript using the parent session's visual language."""

    CSS = APP_CSS + """
    SubagentScreen {
        layout: vertical;
        background: #0a0a0a;
    }

    #subagent-context {
        width: 100%;
        height: 2;
        padding: 0 10;
        color: #737373;
        background: #0a0a0a;
    }

    SubagentScreen #transcript {
        padding-top: 0;
    }

    SubagentScreen #status {
        text-align: right;
    }
    """

    def __init__(self, record: SubagentRecord, workspace: Any = None) -> None:
        super().__init__()
        self.record = record
        self.workspace = Path(workspace or ".").resolve()
        self._thinking = ThinkingStatus("Child working…")
        self._process = RunProcess(self._thinking)
        self._assistant = AssistantMessage()
        self._tools: dict[str, ToolCallWidget] = {}

    def compose(self):  # type: ignore[no-untyped-def]
        yield TopBar(id="topbar")
        yield Static(id="subagent-context")
        with VerticalScroll(id="transcript"):
            yield UserMessage(self.record.prompt or "No task description was provided.")
            yield self._process
            yield self._assistant
        yield Static(id="status")

    def on_mount(self) -> None:
        self.refresh_record()

    def refresh_record(self) -> None:
        """Synchronize live child state into the nested transcript."""
        record = self.record
        topbar = self.query_one("#topbar", TopBar)
        topbar.set_context(self.workspace, record.model_id)

        status_style = {
            "running": "bold #d7a84b",
            "completed": "bold #72a57a",
            "failed": "bold #d66b73",
        }.get(record.status, "bold #737373")
        context = Text()
        context.append("↳  SUBAGENT", style="bold #8ca0cc")
        context.append(f"  {record.label or 'subagent'}", style="#d0d0d0")
        context.append(f"  ·  {record.status}", style=status_style)
        if record.parent_id or record.agent_id:
            parent = record.parent_id.replace("-", "")[:8] or "—"
            child = record.agent_id.replace("-", "")[:8] or "—"
            context.append(f"  ·  {parent} → {child}", style="#626262")
        self.query_one("#subagent-context", Static).update(context)

        for index, tool_data in enumerate(record.tools):
            call_id = str(tool_data.get("id") or f"tool-{index}")
            widget = self._tools.get(call_id)
            if widget is None:
                widget = make_tool_widget(
                    call_id,
                    str(tool_data.get("name") or "tool"),
                )
                self._tools[call_id] = widget
                self._process.add_item(widget)
            status = str(tool_data.get("status") or "preparing")
            arguments = tool_data.get("arguments") or {}
            raw_arguments = str(tool_data.get("raw_arguments") or "")
            if status == "running":
                widget.set_running(arguments)
            elif status in {"done", "failed"}:
                widget.set_result(tool_data.get("result") or "")
                if status == "failed":
                    widget.status = "failed"
                    widget.refresh_content()
            else:
                widget.set_arguments(arguments, raw_arguments)

        if record.status == "running":
            self._thinking.display = True
            self._thinking.set_working(record.label or "subagent")
        else:
            self._thinking.set_text(
                "Child completed" if record.status == "completed" else "Child failed"
            )

        self._assistant.display = bool(record.output_text)
        self._assistant.set_content(record.output_text)
        footer = "live · Esc close" if record.status == "running" else "Esc close"
        self.query_one("#status", Static).update(footer)

        transcript = self.query_one("#transcript", VerticalScroll)
        if transcript.is_vertical_scroll_end:
            self.call_after_refresh(transcript.scroll_end, animate=False)


class SubagentWidget(ToolCallWidget):
    """Clickable parent-transcript row for a child agent."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self.record: Optional[SubagentRecord] = None
        super().__init__(call_id, tool_name)
        self.add_class("subagent-call")

    def _tool_title(self) -> tuple[str, str]:
        return ("Subagent", "↳")

    def _summary(self) -> str:
        return (
            self.record.label
            if self.record
            else str(
                self.arguments.get("label")
                or self.arguments.get("prompt")
                or self.raw_arguments
            )
        )

    def _body_rows(self) -> list[Any]:
        prompt = (
            self.record.prompt
            if self.record
            else str(self.arguments.get("prompt") or "")
        )
        rows: list[Any] = []
        if prompt:
            rows.append(Text(clip_text(prompt, 240), style="#8aa8a5"))
        rows.append(Text("↳  click to open child transcript", style="underline #7186c7"))
        return rows

    def bind(self, record: SubagentRecord) -> None:
        self.record = record
        self.refresh_content()

    def on_bash_tool_header_toggle(self, event: BashToolHeader.Toggle) -> None:
        event.stop()
        self.open_screen()

    def open_screen(self) -> bool:
        record = self.record or SubagentRecord(
            "",
            "",
            str(self.arguments.get("label") or "subagent"),
            str(self.arguments.get("prompt") or ""),
        )
        self.record = record
        workspace = getattr(self.app, "workspace", None)
        self.app.push_screen(SubagentScreen(record, workspace=workspace))
        return True
