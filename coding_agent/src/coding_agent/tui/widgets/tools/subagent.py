"""Clickable spawn_agent row that opens the nested subagent screen."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text

from coding_agent.tui.modal.subagent import SubagentRecord, SubagentScreen
from coding_agent.tui.widgets.tools.base import ToolCallWidget
from coding_agent.utils.text import clip_text


class SubagentWidget(ToolCallWidget):
    """Parent-transcript chip for a child agent."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self.record: Optional[SubagentRecord] = None
        super().__init__(call_id, tool_name)
        self.add_class("subagent-call")

    def _tool_title(self) -> tuple[str, str]:
        return ("Subagent", "↳")

    def _summary(self) -> str:
        if self.record is not None and self.record.label:
            return self.record.label
        return str(self.arguments.get("label") or self.arguments.get("prompt") or self.raw_arguments)

    def bind(self, record: SubagentRecord) -> None:
        self.record = record
        self.refresh_content()

    def set_result(self, result: Any) -> None:
        super().set_result(result)
        if self.record is not None and self.record.status == "running":
            self.record.status = "failed" if self.status == "failed" else "completed"

    def _body_rows(self) -> list[Any]:
        rows: list[Any] = []
        prompt = ""
        if self.record is not None:
            prompt = self.record.prompt
        elif self.arguments.get("prompt"):
            prompt = str(self.arguments["prompt"])
        if prompt:
            rows.append(Text(clip_text(prompt, 240), style="#8aa8a5"))
        hint = Text()
        hint.append("click to open nested session", style="underline #6fb3ae")
        if self.record is not None:
            hint.append(f"  ·  {self.record.status}", style="#666666")
            if self.record.tools:
                hint.append(f"  ·  {len(self.record.tools)} tools", style="#666666")
        rows.append(hint)
        return rows

    def on_bash_tool_header_toggle(self, event: object) -> None:
        stop = getattr(event, "stop", None)
        if callable(stop):
            stop()
        self.open_screen()

    def open_screen(self) -> bool:
        record = self.record
        if record is None:
            record = SubagentRecord(
                agent_id="",
                parent_id="",
                label=str(self.arguments.get("label") or "subagent"),
                prompt=str(self.arguments.get("prompt") or ""),
                status=self.status if self.status in {"running", "done", "failed"} else "running",
            )
            if record.status == "done":
                record.status = "completed"
            record.output_text = self.result
            self.record = record
        self.app.push_screen(SubagentScreen(record))
        return True
