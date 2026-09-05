"""Nested transcript UI for spawned child agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static, OptionList
from textual.widgets.option_list import Option

from coding_agent.tui.chrome import TopBar, render_footer, display_workspace_path
from coding_agent.tui.runtime.events import EventPresenter
from coding_agent.tui.runtime.state import UiRunState
from coding_agent.tui.screens.modal import ModalBase
from coding_agent.tui.theme import APP_CSS
from coding_agent.tui.transcript import (
    UserMessage,
    TranscriptSurface,
)
from coding_agent.tui.tools import BashToolHeader, ToolCallWidget
from coding_agent.tui.transcript import clip_text, compact_json, preview_text


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
    session_id: str = ""
    tool_call_id: str = ""
    run_id: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    _seen_events: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _widgets: list[Any] = field(default_factory=list, repr=False)

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
        if payload.get("parent_id") and (
            payload.get("agent_id") != self.agent_id
            or payload.get("parent_id") != self.parent_id
        ):
            return
        if payload.get("run_id") and isinstance(payload.get("seq"), int):
            key = (str(payload["run_id"]), payload["seq"])
            if key in self._seen_events:
                return
            self._seen_events.add(key)
        self.events.append((event_type, dict(payload)))
        if event_type == "run_started":
            self.run_id = str(payload.get("run_id") or self.run_id)
            self.session_id = str(payload.get("session_id") or self.session_id)
            self.status = "running"
            self.output_text = ""
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
        elif event_type in {"run_failed", "run_cancelled", "run_limit_exceeded", "agent_failed"}:
            self.status = "cancelled" if event_type == "run_cancelled" or payload.get("error_type") == "HarnessCancelled" else "failed"
            if payload.get("message"):
                self.output_text = str(payload["message"])


class SubagentScreen(TranscriptSurface, ModalBase[None]):
    """Full-screen child transcript using the parent session's visual language."""

    # Use the same chrome and transcript surface as the parent app.  This is
    # intentionally not a second, legacy subagent layout: the child prompt is
    # the first user message and the child run uses the normal process cards.
    CSS = APP_CSS + """
    SubagentScreen { border: round #484F58; }
    #child-heading { height: 2; padding: 0 3; color: #a2adb8; }
    #child-back { height: 1; padding: 0 3; color: #737373; }
    """
    BINDINGS = [
        Binding("escape,q", "close_modal", "Back to parent", show=False, priority=True),
        Binding("ctrl+x", "stop_child", "Stop child", show=False, priority=True),
    ]

    def __init__(self, record: SubagentRecord | None = None, workspace: Any = None,
                 *, child_id: str = "", parent_id: str = "") -> None:
        super().__init__()
        self.record = record
        self.child_id = child_id or (record.agent_id if record else "")
        self.parent_id = parent_id or (record.parent_id if record else "")
        self.workspace = Path(workspace or ".").resolve()
        self._thinking = self._process = self._assistant = self._reasoning = None
        self._tools = {}
        self._subagents = {}
        self._transcript_turns = []
        self._current_transcript_turn = None
        self._busy = True
        self._event_cursor = 0
        self._ready = False
        self._stream_flush_timer = None
        self._ui_state = UiRunState()
        self._presenter = EventPresenter(
            state=self._ui_state, view=self, set_status=self._set_status,
            workspace=str(self.workspace), schedule_flush=self._schedule_stream_flush,
        )

    def compose(self):  # type: ignore[no-untyped-def]
        yield TopBar(id="topbar")
        yield Static(id="child-heading", markup=False)
        yield VerticalScroll(id="transcript")
        yield Static("Viewing child transcript · Esc back · Ctrl+X stop child", id="child-back")
        yield Static(id="status")

    def on_mount(self) -> None:
        if self.record is None:
            self.record = getattr(self.app, "_subagents", {}).get(self.child_id)
        if self.record is None or self.record.parent_id != self.parent_id:
            self.add_notice("Child session not found for this parent.", "error")
            return
        self._mount_transcript(UserMessage(self.record.prompt or "Child task"))
        self.live_tool_widget_limit = getattr(self.app, "live_tool_widget_limit", 10)
        self._ready = True
        self.refresh_record()

    def _schedule_stream_flush(self, callback: Any) -> None:
        if self._stream_flush_timer is not None:
            return
        def flush() -> None:
            self._stream_flush_timer = None
            callback()
        self._stream_flush_timer = self.set_timer(1 / 15, flush)

    def on_unmount(self) -> None:
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()

    def _set_status(self, _value: str = "") -> None:
        self.query_one("#status", Static).update(render_footer(
            self._ui_state, hint="esc back", workspace=display_workspace_path(self.workspace),
        ))

    async def action_stop_child(self) -> None:
        await self.app.cancel_subagent(self.child_id)

    def refresh_record(self) -> None:
        """Synchronize live child state into the nested transcript."""
        record = self.record
        if record is None or not self._ready:
            return
        self.query_one("#topbar", TopBar).set_context(
            self.workspace,
            record.model_id,
            label=record.label,
        )

        self.query_one("#child-heading", Static).update(
            f"{record.label} · {record.status} · {record.model_id}\n"
            f"child {record.agent_id[:8]} ← parent {record.parent_id[:8]}"
        )
        for event_type, payload in record.events[self._event_cursor:]:
            self._event_cursor += 1
            if event_type in {"agent_spawned", "agent_completed", "agent_failed"}:
                continue
            if event_type == "run_started" and self._process is not None and self._process.completed:
                self._thinking = self._process = self._assistant = self._reasoning = None
                self._mount_transcript(UserMessage(str(payload.get("prompt") or "Continued child task")))
            if event_type == "question_asked":
                self.add_notice("Waiting for an answer in the parent session.")
                continue
            self._presenter.handle(event_type, payload)
        if record.status != "running":
            self._presenter.flush_stream_paints()
            if self._assistant is None and record.output_text:
                self.set_assistant(record.output_text)
            self.finish_assistant()
            self.finish_reasoning()
            if self._process is None or not self._process.completed:
                self.finish_process(f"Child {record.status}")
            self._ui_state.phase = "idle"
            self._busy = False
        self._set_status()


class SubagentWidget(ToolCallWidget):
    """Clickable parent-transcript row for a child agent."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self.record: Optional[SubagentRecord] = None
        self.keep_in_transcript = True
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
        if self not in record._widgets:
            record._widgets.append(self)
        self.refresh_content()

    def refresh_content(self) -> None:
        if self.record is not None:
            self.status = {"completed": "done", "running": "running"}.get(self.record.status, "failed")
        super().refresh_content()

    def on_bash_tool_header_toggle(self, event: BashToolHeader.Toggle) -> None:
        event.stop()
        self.open_screen()

    def open_screen(self) -> bool:
        if self.record is None:
            self.app.notify("Child is starting; its session will be available shortly.")
            return False
        self.app.open_subagent(self.record)
        return True


class SubagentSurface:
    """Child-agent event wiring mixed into CodingAgentApp."""

    def _bind_spawn_widget(self, record: SubagentRecord) -> None:
        if record.tool_call_id:
            match = self._tools.get(record.tool_call_id)
            if match is None:
                pending = [item for turn in self._transcript_turns for item in turn.timeline_items()]
                match = next((item for item in [*pending, *self.query(SubagentWidget)]
                              if isinstance(item, SubagentWidget)
                              if item.call_id == record.tool_call_id), None)
            if isinstance(match, SubagentWidget):
                match.bind(record)
            return
        candidates = [
            item
            for item in self._tools.values()
            if isinstance(item, SubagentWidget) and item.record is None
        ]
        if not candidates:
            return
        match = next(
            (
                item
                for item in candidates
                if (
                    not record.prompt
                    or item.arguments.get("prompt") == record.prompt
                )
                and (
                    not record.label
                    or item.arguments.get("label") in {record.label, None, ""}
                )
            ),
            None,
        )
        if match is not None:
            match.bind(record)

    def _on_agent_spawned(self, payload: dict[str, Any]) -> None:
        child_id = str(payload.get("child_id") or "")
        if not child_id:
            return
        record = self._subagents.get(child_id) or SubagentRecord(
            agent_id=child_id,
            parent_id=str(payload.get("agent_id") or ""),
            label=str(payload.get("label") or "subagent"),
            prompt=str(payload.get("prompt") or ""),
            model_id=str(payload.get("model_id") or ""),
        )
        record.tool_call_id = str(payload.get("tool_call_id") or record.tool_call_id)
        record.session_id = str(payload.get("child_session_id") or child_id)
        record.label = str(payload.get("label") or record.label)
        record.prompt = str(payload.get("prompt") or record.prompt)
        record.config = {key: payload.get(key) for key in ("model_id", "max_turns", "reasoning_effort")}
        if child_id:
            self._subagents[child_id] = record
        self._bind_spawn_widget(record)
        self._refresh_subagent_screen(record)
        self._refresh_subagent_tasks()

    def _on_agent_finished(self, event_type: str, payload: dict[str, Any]) -> None:
        child_id = str(payload.get("child_id") or "")
        record = self._subagents.get(child_id)
        if record is None:
            return
        if payload.get("agent_id") and payload["agent_id"] != record.parent_id:
            return
        before = len(record.events)
        record.ingest(event_type, payload)
        if len(record.events) == before:
            return
        if getattr(self, "_pending_question_agent_id", "") == child_id:
            from coding_agent.tui.composer import PromptInput, SlashMenu
            self._pending_question_id = None
            self._pending_question_agent_id = ""
            self._pending_question_default = ""
            self.query_one("#slash-menu", SlashMenu).set_commands(())
            self.query_one("#approval-menu", SlashMenu).set_commands(())
            prompt = self.query_one("#prompt", PromptInput)
            prompt.submit_on_enter = False
            prompt.disabled = self._busy
            self._update_composer_hint()
        self._refresh_subagent_widgets(record)
        self._refresh_subagent_screen(record)
        self._refresh_subagent_tasks()
        self.add_notice(f"Subagent {record.label} {record.status} · Ctrl+G to inspect")

    def _on_child_event(self, event_type: str, payload: dict[str, Any]) -> None:
        agent_id = str(payload.get("agent_id") or "")
        if not agent_id or not payload.get("parent_id"):
            return
        record = self._subagents.get(agent_id)
        if record is None:
            record = SubagentRecord(
                agent_id=agent_id,
                parent_id=str(payload.get("parent_id") or ""),
                label="subagent",
                prompt="",
                model_id=str(payload.get("model_id") or ""),
            )
            if agent_id:
                self._subagents[agent_id] = record
            self._bind_spawn_widget(record)
        record.ingest(event_type, payload)
        self._refresh_subagent_widgets(record)
        self._refresh_subagent_screen(record)

    def _show_child_question(self, payload: Mapping[str, Any]) -> None:
        """Surface child questions through the parent's interactive composer."""
        if isinstance(self.screen, SubagentScreen):
            self.screen.dismiss(None)
            self.call_after_refresh(self._show_question, dict(payload))
            return
        self._show_question(payload)

    def _refresh_subagent_widgets(self, record: SubagentRecord) -> None:
        for widget in record._widgets:
            if isinstance(widget, SubagentWidget) and widget.record is record:
                widget.refresh_content()

    def _refresh_subagent_screen(self, record: SubagentRecord) -> None:
        screen = self.screen
        if isinstance(screen, SubagentScreen) and screen.child_id == record.agent_id:
            screen.refresh_record()

    def open_subagent(self, record: SubagentRecord) -> None:
        self._subagents[record.agent_id] = record
        self.push_screen(SubagentScreen(child_id=record.agent_id, parent_id=record.parent_id, workspace=self.workspace))

    def action_subagents(self) -> None:
        self.push_screen(SubagentTasksScreen())

    def _refresh_subagent_tasks(self) -> None:
        if isinstance(self.screen, SubagentTasksScreen):
            self.screen.refresh_tasks()

    async def cancel_subagent(self, child_id: str) -> None:
        harness = getattr(self._agent, "harness", None)
        record = getattr(harness, "child_tasks", {}).get(child_id)
        if record is not None and record.task is not None and not record.task.done():
            import asyncio
            record.task.cancel()
            await asyncio.gather(record.task, return_exceptions=True)

    async def restore_subagents(self) -> None:
        if self._agent is None:
            return
        store = self._agent.persistence
        load = getattr(store, "load_children", None)
        if not callable(load):
            return
        for metadata in await load(parent_session_id=self._agent.session_id):
            child_id = metadata["child_id"]
            if child_id in self._subagents:
                continue
            self._on_agent_spawned(metadata)
            record = self._subagents[child_id]
            for event_type, payload in await store.load_events(session_id=record.session_id):
                record.ingest(event_type, payload)
            record.status = metadata["status"]
            record.output_text = metadata["output_text"] or record.output_text
            if record.status == "running":
                record.status = "interrupted"
            self._refresh_subagent_widgets(record)


class SubagentTasksScreen(ModalBase[None]):
    """Stable access to child sessions even after parent transcript compaction."""

    CSS = """
    SubagentTasksScreen { align: center middle; background: #000000 60%; }
    #subagent-tasks { width: 90%; height: 70%; border: round #484F58; background: #0A0A0A; }
    """

    def compose(self):
        yield OptionList(id="subagent-tasks")

    def on_mount(self) -> None:
        self.query_one(OptionList).border_title = "Subagents · Enter inspect · Esc back"
        self.refresh_tasks()
        self.query_one(OptionList).focus()

    def refresh_tasks(self) -> None:
        options = self.query_one(OptionList)
        highlighted = options.highlighted
        options.clear_options()
        records = list(getattr(self.app, "_subagents", {}).values())
        for record in records:
            color = {"running": "#d7a84b", "completed": "#72a57a"}.get(record.status, "#d66b73")
            label = Text(f"{record.status:12} ", style=color)
            label.append(f"{record.label} · {record.model_id} · {record.agent_id[:8]}")
            options.add_option(Option(label, id=record.agent_id))
        if not records:
            options.add_option(Option("No child sessions yet.", disabled=True))
        else:
            options.highlighted = min(highlighted or 0, len(records) - 1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        record = self.app._subagents.get(event.option.id)
        if record is not None:
            self.dismiss(None)
            self.app.call_after_refresh(self.app.open_subagent, record)
