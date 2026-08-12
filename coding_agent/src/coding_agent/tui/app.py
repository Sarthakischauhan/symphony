"""A conversation-first Textual interface for the Symphony coding agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from coding_agent.agent import AgentMode, CodingAgent
from coding_agent.plan import PlanStore
from coding_agent.tui.commands import command_matches, mode_matches, model_matches
from coding_agent.tui.commands.command_manager import CommandManager
from coding_agent.tui.commands.mode_switcher import toggle_mode
from coding_agent.tui.control_plane import HarnessEvent, TextualControlPlane
from coding_agent.tui.events import EventPresenter
from coding_agent.tui.agent_factory import build_agent
from coding_agent.tui.history import load_session_history
from coding_agent.tui.state import UiRunState
from coding_agent.tui.status import render_status
from coding_agent.tui.styles.app import APP_CSS
from coding_agent.tui.theme import SYMPHONY_RICH_THEME
from coding_agent.tui.widgets import (
    AssistantMessage,
    Composer,
    Notice,
    ReasoningWidget,
    RunProcess,
    SlashMenu,
    ThinkingStatus,
    TopBar,
    ToolCallWidget,
    UserMessage,
    Welcome,
    make_tool_widget,
)
from core_harness import HarnessResult


class CodingAgentApp(App[None]):
    """Full-screen chat transcript backed by core_harness events."""

    CSS = APP_CSS
    # Keep terminal mouse drag selection enabled for transcript content.
    ALLOW_SELECT = True

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
        self.mode: AgentMode = "build"
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
        self._plan_store = PlanStore(self.workspace)
        self._plan_run_active = False
        self._pending_question_id: str | None = None
        self._pending_question_default = ""
        self._command_manager = CommandManager(self)

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with VerticalScroll(id="transcript"):
            yield Welcome(self.workspace)
        yield SlashMenu(id="slash-menu")
        yield Composer(id="composer")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        self.control_plane.bind(self)
        self._presenter = EventPresenter(
            state=self._ui_state,
            view=self,
            set_status=self._set_status,
            workspace=str(self.workspace),
        )
        topbar = self.query_one("#topbar", TopBar)
        topbar.set_context(self.workspace, self.model_id or os.getenv("OPENAI_MODEL", ""))
        self._update_composer_hint()

        try:
            self._agent = build_agent(
                workspace=self.workspace,
                control_plane=self.control_plane,
                model_id=self.model_id,
                session_id=self.session_id,
            )
            self._agent.set_mode(self.mode)
        except Exception as exc:  # noqa: BLE001
            self._set_status("")
            self.add_notice(f"Offline · {exc}. Add it to .env and restart.", "error")
            self.query_one("#prompt", Input).focus()
            return

        self._ui_state.model_id = self._agent.harness.model_id
        self._ui_state.metrics.context_limit = self._agent.harness.state.context_limit(
            self._ui_state.model_id
        )
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
        self.query_one("#status", Static).update(render_status(self._ui_state, self.workspace))

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None:
        """Restore context usage for a resumed session before its first run."""
        metrics = self._ui_state.metrics
        metrics.tokens_used = tokens_used
        metrics.context_limit = context_limit
        metrics.context_left = max(context_limit - tokens_used, 0)
        metrics.utilization = tokens_used / context_limit if context_limit else None
        self._set_status("")

    @work(exclusive=False)
    async def load_session_history(self) -> None:
        if self._agent is None:
            return
        await load_session_history(self._agent, self)

    def mount_transcript(self, widget: Static) -> None:
        """Public adapter used by the persisted-history loader."""
        self._mount_transcript(widget)

    def on_harness_event(self, message: HarnessEvent) -> None:
        if self._plan_run_active and message.event_type == "text_delta":
            self._plan_store.append(str(message.payload.get("delta") or ""))
            return
        if message.event_type == "question_asked":
            self._show_question(message.payload)
            return
        if self._presenter is not None:
            self._presenter.handle(message.event_type, message.payload)
        if self._plan_run_active and message.event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
        }:
            self._plan_run_active = False

    on_control_plane_event = on_harness_event

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        if self._pending_question_id is not None:
            await self._answer_question(text or self._pending_question_default)
            return
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
        if self.mode == "plan":
            self._plan_store.begin(text)
            self._plan_run_active = True
        self._busy = True
        event.input.disabled = True
        self.query_one("#composer-hint", Static).update("Working…")
        self.run_agent(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        if self._pending_question_id is not None:
            return
        menu = self.query_one("#slash-menu", SlashMenu)
        if event.value.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(model_matches(event.value.removeprefix("/model ")), current)
        elif event.value.startswith("/mode "):
            menu.set_modes(mode_matches(event.value.removeprefix("/mode ")), self.mode)
        elif event.value.startswith("/plan "):
            menu.set_plans(
                self._command_manager.plan_options(event.value.removeprefix("/plan ")),
                self._plan_store.path.name,
            )
        else:
            menu.set_commands(command_matches(event.value))

    def on_key(self, event: events.Key) -> None:
        """Navigate, choose, or complete the visible slash menu."""
        prompt = self.query_one("#prompt", Input)
        if not prompt.has_focus:
            return
        menu = self.query_one("#slash-menu", SlashMenu)
        if not menu.display:
            if event.key == "tab" and not self._busy:
                toggle_mode(self)
                event.prevent_default()
                event.stop()
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
        elif event.key == "enter" and self._pending_question_id is not None:
            self.call_later(prompt.action_submit)
            event.prevent_default()
            event.stop()

    async def _run_slash_command(self, value: str) -> None:
        await self._command_manager.run(value)

    def _update_composer_hint(self) -> None:
        label = self.mode.upper()
        self.query_one("#composer", Composer).set_class(
            self.mode == "plan", "plan-mode"
        )
        hint = f"{label} · Tab mode · Enter to send"
        if self._pending_question_id is not None:
            hint = "Waiting for your answer…"
        self.query_one("#composer-hint", Static).update(hint)

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
            self._update_composer_hint()
            prompt.focus()

    async def _run_agent_turn(self, user_input: str) -> HarnessResult:
        assert self._agent is not None
        mode = self.mode
        result = await self._agent.run(user_input)
        if mode == "plan":
            self._command_manager.open_plan_modal()
        return result

    def action_clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        transcript.mount(Welcome(self.workspace))
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools.clear()

    def _show_question(self, payload: Mapping[str, Any]) -> None:
        request_id = str(payload.get("request_id") or "")
        question = str(payload.get("question") or "")
        choices = [str(choice) for choice in payload.get("choices") or []]
        default = str(payload.get("default") or "")
        if not request_id or not question:
            self.add_notice("The agent sent an invalid question request.", "error")
            return
        self._pending_question_id = request_id
        self._pending_question_default = default
        self._ui_state.phase = "paused"
        self._ui_state.detail = "waiting for user"
        self._update_composer_hint()
        menu = self.query_one("#slash-menu", SlashMenu)
        menu.set_question(question, choices, default=default)
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.value = default
        prompt.cursor_position = len(default)
        prompt.focus()

    async def _answer_question(self, answer: str) -> None:
        request_id = self._pending_question_id
        if request_id is None:
            return
        self._pending_question_id = None
        self._pending_question_default = ""
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        await self.control_plane.answer_user(request_id, answer)
        self._ui_state.phase = "thinking"
        self._ui_state.detail = "resuming"
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = True
        self._update_composer_hint()


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Load environment configuration and launch the terminal UI."""
    load_dotenv(override=True)
    CodingAgentApp(workspace=workspace, model_id=model_id, session_id=session_id).run()
