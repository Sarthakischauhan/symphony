"""A conversation-first Textual interface for the Symphony coding agent."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from coding_agent.agent import CodingAgent
from coding_agent.tui.commands import (
    MODEL_CATALOG,
    SLASH_COMMANDS,
    command_matches,
    find_model,
    model_matches,
)
from coding_agent.tui.control_plane import HarnessEvent, TextualControlPlane
from coding_agent.tui.events import EventPresenter
from coding_agent.tui.state import UiRunState
from coding_agent.tui.widgets import (
    AssistantMessage,
    Composer,
    Notice,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    ToolCallWidget,
    TopBar,
    UserMessage,
    Welcome,
    SlashMenu,
    make_tool_widget,
)
from core_harness import HarnessResult


def _build_agent(
    *,
    workspace: Path,
    control_plane: TextualControlPlane,
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> CodingAgent:
    from core_ai import ModelRegistry
    from core_ai.providers.openai import OpenAIProvider

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = model_id or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    if ":" not in model_name:
        model_name = f"openai:{model_name}"
    registry = ModelRegistry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))
    return CodingAgent(
        registry=registry,
        model_id=model_name,
        workspace=workspace,
        control_plane=control_plane,
        session_id=session_id,
    )


class CodingAgentApp(App[None]):
    """Full-screen chat transcript backed by core_harness events."""

    CSS = """
    $background: #181818;
    $panel: #202020;
    $panel-light: #292929;
    $line: #393939;
    $muted: #727272;

    Screen {
        layout: vertical;
        background: $background;
        color: #d4d4d4;
    }

    #topbar {
        height: 3;
        padding: 1 3 0 3;
        background: $background;
    }

    #transcript {
        width: 100%;
        height: 1fr;
        padding: 1 10 2 10;
        scrollbar-size: 1 1;
        scrollbar-color: #484848;
        scrollbar-color-hover: #606060;
        scrollbar-background: $background;
    }

    .welcome {
        width: 72;
        height: auto;
        min-height: 10;
        margin: 2 0 1 2;
        padding: 1 2;
        border-left: thick #777777;
        color: #bcbcbc;
    }

    .message {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 1 2;
    }

    .user-message {
        background: $panel-light;
        border-left: solid #777777;
    }

    .assistant-message {
        padding-left: 1;
        background: $background;
    }

    .thinking-status {
        width: 100%;
        height: 2;
        padding: 0 0 0 3;
        color: $muted;
    }

    .run-process {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0 0 0 1;
        border-top: none;
        background: $background;
    }

    .run-process > CollapsibleTitle {
        width: auto;
        padding: 0 1;
        color: #666666;
        background: $background;
    }

    .run-process > CollapsibleTitle:hover {
        color: #a0a0a0;
        background: #202020;
    }

    .run-process > Contents {
        padding: 0 0 0 1;
    }

    .reasoning-summary {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2 0 3;
        color: #777777;
        border-left: solid #343434;
    }

    .tool-call {
        width: 100%;
        height: auto;
        min-height: 2;
        margin: 0 0 0 1;
        padding: 0 1;
        border-left: solid #383838;
        background: $background;
    }

    .diff-tool {
        margin-top: 1;
        margin-bottom: 1;
        padding-bottom: 1;
        background: #1b1b1b;
        border-left: solid #454545;
    }

    .notice {
        width: 100%;
        height: auto;
        min-height: 1;
        margin: 0 0 0 1;
        color: $muted;
    }

    #composer {
        width: 1fr;
        height: 6;
        margin: 0 10 1 10;
        padding: 0;
        background: $panel;
        border: solid #505050;
    }

    #slash-menu {
        display: none;
        width: 1fr;
        height: auto;
        max-height: 10;
        margin: 0 10;
        padding: 1 1 0 1;
        background: #202020;
        border: solid #3f3f3f;
        border-bottom: none;
    }

    #composer:focus-within {
        border: solid #888888;
    }

    #prompt {
        width: 100%;
        height: 3;
        padding: 0 1;
        border: none;
        background: $panel;
        color: #eeeeee;
    }

    #prompt:focus {
        border: none;
    }

    #prompt.-disabled {
        color: #777777;
    }

    #composer-hint {
        height: 1;
        padding: 0 1;
        color: #595959;
        text-align: right;
        background: $panel;
    }

    #status {
        width: 100%;
        height: 1;
        padding: 0 3;
        background: #141414;
        color: #686868;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
    ]

    TITLE = "Symphony"

    def __init__(
        self,
        *,
        workspace: str | Path = ".",
        model_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.model_id = model_id
        self.session_id = session_id
        self.control_plane = TextualControlPlane()
        self._agent: Optional[CodingAgent] = None
        self._busy = False
        self._ui_state = UiRunState()
        self._presenter: Optional[EventPresenter] = None
        self._assistant: Optional[AssistantMessage] = None
        self._thinking: Optional[ThinkingStatus] = None
        self._reasoning: Optional[ReasoningWidget] = None
        self._process: Optional[RunProcess] = None
        self._tools: dict[str, ToolCallWidget] = {}

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with VerticalScroll(id="transcript"):
            yield Welcome(self.workspace)
        yield SlashMenu(id="slash-menu")
        yield Composer(id="composer")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.control_plane.bind(self)
        self._presenter = EventPresenter(
            state=self._ui_state,
            view=self,
            set_status=self._set_status,
            workspace=str(self.workspace),
        )
        topbar = self.query_one("#topbar", TopBar)
        topbar.set_context(self.workspace, self.model_id or os.getenv("OPENAI_MODEL", ""))

        try:
            self._agent = _build_agent(
                workspace=self.workspace,
                control_plane=self.control_plane,
                model_id=self.model_id,
                session_id=self.session_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status("")
            self.add_notice(f"Offline · {exc}. Add it to .env and restart.", "error")
            self.query_one("#prompt", Input).focus()
            return

        self._ui_state.model_id = self._agent.harness.model_id
        self._ui_state.phase = "idle"
        self._ui_state.detail = "ready"
        topbar.set_context(self.workspace, self._ui_state.model_id)
        self._presenter.refresh_chrome()
        if self.session_id:
            self.load_session_history()
        self.query_one("#prompt", Input).focus()

    # TranscriptView implementation
    def _mount_transcript(self, widget: Static) -> None:
        welcome = self.query(".welcome")
        if welcome:
            welcome.first().remove()
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(widget)
        self.call_after_refresh(transcript.scroll_end, animate=False)

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        if new or self._assistant is None:
            self._assistant = AssistantMessage(text)
            self._mount_transcript(self._assistant)
        else:
            self._assistant.set_content(text)
        transcript = self.query_one("#transcript", VerticalScroll)
        self.call_after_refresh(transcript.scroll_end, animate=False)

    def set_thinking(self, text: str) -> None:
        if self._thinking is None:
            self._thinking = ThinkingStatus(text)
            self._process = RunProcess(self._thinking)
            self._mount_transcript(self._process)
        else:
            self._thinking.set_text(text)

    def _mount_process_item(self, widget: Static) -> None:
        if self._process is None:
            self.set_thinking("Thinking…")
        assert self._process is not None
        self._process.add_item(widget)
        transcript = self.query_one("#transcript", VerticalScroll)
        self.call_after_refresh(transcript.scroll_end, animate=False)

    def set_reasoning(self, text: str, *, new: bool = False) -> None:
        if new or self._reasoning is None:
            self._reasoning = ReasoningWidget(text)
            self._mount_process_item(self._reasoning)
        else:
            self._reasoning.set_content(text)
        transcript = self.query_one("#transcript", VerticalScroll)
        self.call_after_refresh(transcript.scroll_end, animate=False)

    def add_tool(self, call_id: str, name: str) -> None:
        widget = make_tool_widget(call_id, name)
        self._tools[call_id] = widget
        self._mount_process_item(widget)

    def update_tool(
        self,
        call_id: str,
        *,
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None:
        widget = self._tools.get(call_id)
        if widget is None:
            self.add_tool(call_id, "tool")
            widget = self._tools[call_id]
        if status == "running":
            widget.set_running(arguments)
        elif status == "done":
            widget.set_result(result)
        else:
            widget.set_arguments(arguments, raw_arguments)
        transcript = self.query_one("#transcript", VerticalScroll)
        self.call_after_refresh(transcript.scroll_end, animate=False)

    def add_notice(self, text: str, tone: str = "info") -> None:
        notice = Notice(text, tone)
        if self._busy and self._process is not None:
            self._mount_process_item(notice)
        else:
            self._mount_transcript(notice)

    def finish_process(self, title: str, *, collapse: bool = True) -> None:
        if self._process is not None:
            self._process.complete(title, collapse=collapse)

    def _set_status(self, _value: str) -> None:
        m = self._ui_state.metrics
        phase = (
            "working"
            if self._ui_state.phase not in {"idle", "paused"}
            else self._ui_state.phase
        )
        color = "#d7a84b" if phase == "working" else "#72a57a" if phase == "idle" else "#888888"
        line = Text("● ", style=color)
        line.append(phase, style="#858585")
        if m.cumulative_tokens or m.total_tokens:
            line.append(f"   {m.cumulative_tokens or m.total_tokens:,} tokens", style="#5e5e5e")
        if m.context_limit and m.context_left is not None:
            used = 1 - (m.context_left / m.context_limit)
            line.append(f"   context {used:.0%}", style="#5e5e5e")
        line.append(f"   {self.workspace}", style="#4f4f4f")
        self.query_one("#status", Static).update(line)

    @work(exclusive=False)
    async def load_session_history(self) -> None:
        if self._agent is None:
            return
        messages = await self._agent.persistence.load_conversation(
            session_id=self._agent.session_id
        )
        self.add_notice(f"Resumed session · {self._agent.session_id}")
        pending_tools: dict[str, ToolCallWidget] = {}
        for message in messages:
            content = (
                message.content
                if isinstance(message.content, str)
                else json.dumps(message.content, ensure_ascii=False)
            )
            if message.role == "user":
                self._mount_transcript(UserMessage(content))
            elif message.role == "assistant":
                if content:
                    self._mount_transcript(AssistantMessage(content))
                for call in message.tool_calls or []:
                    call_id = str(call.get("id") or "history-tool")
                    function = call.get("function") or {}
                    name = str(function.get("name") or call.get("name") or "tool")
                    widget = make_tool_widget(call_id, name)
                    raw = function.get("arguments") or call.get("arguments") or ""
                    try:
                        args = json.loads(raw) if isinstance(raw, str) else raw
                    except json.JSONDecodeError:
                        args = {}
                    widget.set_running(args if isinstance(args, dict) else {})
                    pending_tools[call_id] = widget
                    self._mount_transcript(widget)
            elif message.role == "tool":
                widget = pending_tools.get(str(message.tool_call_id))
                if widget:
                    widget.set_result(content)

    def on_harness_event(self, message: HarnessEvent) -> None:
        if self._presenter is not None:
            self._presenter.handle(message.event_type, message.payload)

    on_control_plane_event = on_harness_event

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        if not text:
            return
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        if text.startswith("/"):
            await self._run_slash_command(text)
            return
        if self._agent is None:
            self.add_notice("Agent is offline. Configure OPENAI_API_KEY and restart.", "error")
            return
        if self._busy:
            self.add_notice("A turn is already in progress.", "warning")
            return

        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools = {}
        self._mount_transcript(UserMessage(text))
        self.set_thinking("Thinking…")
        self._busy = True
        event.input.disabled = True
        self.query_one("#composer-hint", Static).update("Working…")
        self.run_agent(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        menu = self.query_one("#slash-menu", SlashMenu)
        if event.value.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(model_matches(event.value.removeprefix("/model ")), current)
        else:
            menu.set_commands(command_matches(event.value))

    def on_key(self, event: events.Key) -> None:
        """Navigate, choose, or complete the visible slash menu."""
        prompt = self.query_one("#prompt", Input)
        if not prompt.has_focus:
            return
        menu = self.query_one("#slash-menu", SlashMenu)
        if not menu.display:
            return

        if event.key in {"up", "down"}:
            menu.move_selection(-1 if event.key == "up" else 1)
            event.prevent_default()
            event.stop()
            return
        if event.key in {"tab", "enter"} and menu.selected_value:
            prompt.value = menu.selected_value
            prompt.cursor_position = len(prompt.value)
            if event.key == "enter":
                menu.set_commands(())
                self.call_later(prompt.action_submit)
            event.prevent_default()
            event.stop()

    async def _run_slash_command(self, value: str) -> None:
        command, _, argument = value[1:].partition(" ")
        command = command.lower().strip()
        argument = argument.strip()

        if command in {"quit", "exit"}:
            self.exit()
            return
        if command == "clear":
            self.action_clear_transcript()
            return
        if command == "help":
            lines = [f"{item.usage:<24} {item.description}" for item in SLASH_COMMANDS]
            self.add_notice("Slash commands\n" + "\n".join(lines))
            return
        if command == "status":
            self._show_command_status()
            return
        if self._busy:
            self.add_notice(f"/{command} is unavailable while a turn is running.", "warning")
            return
        if self._agent is None:
            self.add_notice("Agent is offline. Configure OPENAI_API_KEY and restart.", "error")
            return
        if command == "new":
            self._start_new_session()
            return
        if command == "model":
            if argument:
                self._select_model(argument)
            else:
                prompt = self.query_one("#prompt", Input)
                prompt.value = "/model "
                prompt.cursor_position = len(prompt.value)
                self.query_one("#slash-menu", SlashMenu).set_models(
                    MODEL_CATALOG,
                    self._agent.harness.model_id,
                )
            return
        if command == "compact":
            before, after = await self._agent.compact_conversation()
            if before == 0:
                self.add_notice("There is no saved conversation to compact.")
            elif before == after:
                self.add_notice(f"Context is already compact · {after} messages")
            return

        self.add_notice(f"Unknown command: /{command}. Type /help to see commands.", "warning")

    def _select_model(self, argument: str) -> None:
        assert self._agent is not None
        selected = find_model(argument)
        if selected is None:
            self.add_notice(
                f"Unknown model: {argument}. Run /model to see available models.",
                "warning",
            )
            return
        self._agent.harness.model_id = selected.id
        if self._agent.learning_loop is not None:
            self._agent.learning_loop.model_id = selected.id
        self.model_id = selected.id
        self._ui_state.model_id = selected.id
        self._ui_state.metrics.context_limit = self._agent.harness.state.context_limit(
            selected.id
        )
        self.query_one("#topbar", TopBar).set_context(self.workspace, selected.id)
        self._set_status("")
        self.add_notice(f"Model switched to {selected.label} · {selected.id}", "success")

    def _start_new_session(self) -> None:
        assert self._agent is not None
        session_id = str(uuid.uuid4())
        self.session_id = session_id
        self._agent.session_id = session_id
        self._agent.harness.session_id = session_id
        self._ui_state.reset_for_run(model_id=self._agent.harness.model_id)
        self._ui_state.phase = "idle"
        self._ui_state.detail = "ready"
        self.action_clear_transcript()
        self.add_notice(f"New conversation · {session_id[:8]}", "success")
        self._set_status("")

    def _show_command_status(self) -> None:
        if self._agent is None:
            self.add_notice("Status · offline", "warning")
            return
        m = self._ui_state.metrics
        context = "unknown"
        if m.context_limit is not None and m.context_left is not None:
            context = f"{m.context_left:,} / {m.context_limit:,} tokens left"
        self.add_notice(
            "Status\n"
            f"model     {self._agent.harness.model_id}\n"
            f"session   {self._agent.session_id}\n"
            f"context   {context}"
        )

    @work(exclusive=True)
    async def run_agent(self, user_input: str) -> None:
        try:
            await self._run_agent_turn(user_input)
        except Exception as exc:  # noqa: BLE001
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
            if self._ui_state.detail != "failed":
                self.add_notice(f"Error · {exc}", "error")
        finally:
            if self._presenter is not None:
                self._ui_state.phase = "idle"
                self._presenter.refresh_chrome()
            self._busy = False
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            self.query_one("#composer-hint", Static).update("Enter to send")
            prompt.focus()

    async def _run_agent_turn(self, user_input: str) -> HarnessResult:
        assert self._agent is not None
        return await self._agent.run(user_input)

    def action_clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        transcript.mount(Welcome(self.workspace))
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools.clear()


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Load environment configuration and launch the terminal UI."""
    load_dotenv(override=True)
    CodingAgentApp(workspace=workspace, model_id=model_id, session_id=session_id).run()
