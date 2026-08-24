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
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static, TextArea

from coding_agent.agent import AgentMode, CodingAgent
from coding_agent.plan import PlanStore
from coding_agent.tui.commands import command_matches, mode_matches, model_matches
from coding_agent.tui.commands.command_manager import CommandManager
from coding_agent.tui.commands.mode_switcher import toggle_mode
from coding_agent.tui.control_plane import HarnessEvent, TextualControlPlane
from coding_agent.tui.events import EventPresenter
from coding_agent.tui.file_selector import (
    active_file_mention,
    complete_file_mention,
    file_matches,
)
from coding_agent.tui.agent_factory import build_agent
from coding_agent.tui.history import load_session_history
from coding_agent.tui.images import build_user_content
from coding_agent.tui.slash_menu import SlashMenu
from coding_agent.tui.state import UiRunState
from coding_agent.tui.status import render_status
from coding_agent.tui.styles.app import APP_CSS
from coding_agent.tui.theme import SYMPHONY_RICH_THEME
from coding_agent.tui.widgets import (
    AssistantMessage,
    Composer,
    Notice,
    PromptInput,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    TopBar,
    ToolCallWidget,
    UserMessage,
    Welcome,
    make_tool_widget,
)
from core_ai.types import Content
from core_harness import HarnessCancelled, HarnessLimitExceeded, HarnessResult


class CodingAgentApp(App[None]):
    """Full-screen chat transcript backed by core_harness events."""

    CSS = APP_CSS
    # Keep terminal mouse drag selection enabled for transcript content.
    ALLOW_SELECT = True

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("escape", "cancel_run", "Cancel", show=True, priority=True),
        Binding("ctrl+x", "cancel_run", "Cancel", show=False, priority=True),
    ]

    TITLE = "Symphony"

    def __init__(
        self,
        *,
        workspace: str | Path = ".",
        model_id: Optional[str] = None,
        session_id: Optional[str] = None,
        enable_learning: bool = True,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.model_id = model_id
        self.session_id = session_id
        self.enable_learning = enable_learning
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
        self.set_interval(1, lambda: self._set_status(""))

        try:
            self._agent = build_agent(
                workspace=self.workspace,
                control_plane=self.control_plane,
                model_id=self.model_id,
                session_id=self.session_id,
                enable_learning=self.enable_learning,
            )
            self._agent.set_mode(self.mode)
        except Exception as exc:  # noqa: BLE001
            self._set_status("")
            self.add_notice(f"Offline · {exc}. Add it to .env and restart.", "error")
            self.query_one("#prompt", PromptInput).focus()
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
        self.query_one("#prompt", PromptInput).focus()

    # TranscriptView implementation
    def _follow_transcript_tail(
        self, transcript: VerticalScroll, *, was_at_end: bool
    ) -> None:
        """Keep following live output unless the user has scrolled away."""
        if was_at_end:
            self.call_after_refresh(transcript.scroll_end, animate=False)

    def _mount_transcript(self, widget: Static) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        welcome = self.query(".welcome")
        if welcome:
            welcome.first().remove()
        transcript.mount(widget)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        if new or self._assistant is None:
            self._assistant = AssistantMessage(text)
            self._mount_transcript(self._assistant)
        else:
            transcript = self.query_one("#transcript", VerticalScroll)
            was_at_end = transcript.is_vertical_scroll_end
            self._assistant.set_content(text)
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def set_thinking(self, text: str) -> None:
        if self._thinking is None:
            self._thinking = ThinkingStatus(text)
            self._process = RunProcess(self._thinking)
            self._mount_transcript(self._process)
        else:
            self._thinking.set_text(text)

    def set_working(self, detail: str = "") -> None:
        if self._thinking is None:
            self.set_thinking("Working")
        assert self._thinking is not None
        self._thinking.display = True
        self._thinking.set_working(detail)

    def _mount_process_item(self, widget: Widget) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        if self._process is None:
            self.set_thinking("Thinking…")
        assert self._process is not None
        self._process.add_item(widget)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def set_reasoning(self, text: str, *, new: bool = False) -> None:
        if new or self._reasoning is None:
            if self._thinking is not None:
                self._thinking.display = False
            self._reasoning = ReasoningWidget(text)
            self._mount_process_item(self._reasoning)
        else:
            transcript = self.query_one("#transcript", VerticalScroll)
            was_at_end = transcript.is_vertical_scroll_end
            self._reasoning.set_content(text)
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def finish_reasoning(self) -> None:
        if self._reasoning is None:
            return
        self._reasoning.complete()
        self._reasoning = None

    def add_tool(self, call_id: str, name: str) -> None:
        if self._thinking is not None:
            self._thinking.display = False
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
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
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
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

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

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        text = event.input.expanded_value(event.input.text).strip()
        pasted_chunks = event.input.take_pasted_chunks()
        event.input.load_text("")
        if self._pending_question_id is not None:
            event.input.take_images()
            await self._answer_question(text or self._pending_question_default)
            return
        if not text:
            event.input.take_images()
            return
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        if text.startswith("/"):
            event.input.take_images()
            await self._run_slash_command(text)
            return
        images = event.input.take_images()
        if self._agent is None:
            self.add_notice("Agent is offline. Configure OPENAI_API_KEY and restart.", "error")
            return
        if self._busy:
            self.add_notice("A turn is already in progress.", "warning")
            return

        user_content = build_user_content(text, images)
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools = {}
        self._mount_transcript(
            UserMessage(text, pasted_chunks=pasted_chunks, images=images)
        )
        self.set_thinking("Thinking…")
        if self.mode == "plan":
            self._plan_store.begin(text)
            self._plan_run_active = True
        self._busy = True
        event.input.disabled = True
        self.query_one("#composer-hint", Static).update("Working…   Esc cancel")
        self.run_agent(user_content)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        if self._pending_question_id is not None:
            return
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        menu = (
            approval_menu
            if approval_menu.display
            else self.query_one("#slash-menu", SlashMenu)
        )
        mention = active_file_mention(event.text_area.text)
        if mention is not None:
            _start, query = mention
            menu.set_files(file_matches(self.workspace, query))
        elif event.text_area.text.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(model_matches(event.text_area.text.removeprefix("/model ")), current)
        elif event.text_area.text.startswith("/mode "):
            menu.set_modes(mode_matches(event.text_area.text.removeprefix("/mode ")), self.mode)
        elif event.text_area.text.startswith("/plan "):
            menu.set_plans(
                self._command_manager.plan_options(event.text_area.text.removeprefix("/plan ")),
                self._plan_store.path.name,
            )
        else:
            menu.set_commands(command_matches(event.text_area.text))

    def on_key(self, event: events.Key) -> None:
        """Navigate, choose, or complete the visible slash menu."""
        prompt = self.query_one("#prompt", PromptInput)
        if not prompt.has_focus:
            return
        if event.key in {"ctrl+enter", "control+enter"}:
            prompt.action_submit()
            event.prevent_default()
            event.stop()
            return
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        menu = (
            approval_menu
            if approval_menu.display
            else self.query_one("#slash-menu", SlashMenu)
        )
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
            self._choose_menu_option(menu, submit=event.key == "enter")
            event.prevent_default()
            event.stop()
        elif event.key == "enter" and self._pending_question_id is not None:
            self.call_later(prompt.action_submit)
            event.prevent_default()
            event.stop()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Apply menu choices selected with the pointer."""
        if event.option_list.id not in {"slash-menu", "approval-menu"}:
            return
        menu = event.option_list
        assert isinstance(menu, SlashMenu)
        if menu.select_option_index(event.option_index):
            self._choose_menu_option(menu, submit=True)
        event.stop()

    def _choose_menu_option(self, menu: SlashMenu, *, submit: bool) -> None:
        prompt = self.query_one("#prompt", PromptInput)
        if self._pending_question_id is not None and submit:
            answer = menu.selected_value
            menu.set_commands(())
            prompt.load_text("")
            self.call_later(self._answer_question, answer)
            prompt.focus()
            return
        if menu.is_file_selector:
            prompt.value, cursor = complete_file_mention(
                prompt.value,
                menu.selected_value.removeprefix("@"),
            )
            prompt.cursor_position = cursor
            menu.set_commands(())
        else:
            prompt.value = menu.selected_value
            prompt.cursor_position = len(prompt.value)
            if submit:
                menu.set_commands(())
                self.call_later(prompt.action_submit)
        prompt.focus()

    async def _run_slash_command(self, value: str) -> None:
        await self._command_manager.run(value)

    def _update_composer_hint(self) -> None:
        label = self.mode.upper()
        self.query_one("#composer", Composer).set_class(
            self.mode == "plan", "plan-mode"
        )
        self.query_one("#composer-mode", Static).update(f"{label} · Tab mode")
        hint = "Ctrl+↵ send   Enter line break   Esc cancel"
        if self._pending_question_id is not None:
            hint = "↵ approve   ↑↓ choose   Esc deny"
        self.query_one("#composer-hint", Static).update(hint)

    @work(exclusive=True)
    async def run_agent(self, user_input: Content) -> None:
        try:
            await self._run_agent_turn(user_input)
        except (HarnessCancelled, HarnessLimitExceeded):
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
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
            self._pending_question_id = None
            self._pending_question_default = ""
            self.control_plane.reset_cancel()
            prompt = self.query_one("#prompt", PromptInput)
            prompt.submit_on_enter = False
            prompt.disabled = False
            self._update_composer_hint()
            prompt.focus()

    async def _run_agent_turn(self, user_input: Content) -> HarnessResult:
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

    def action_cancel_run(self) -> None:
        if isinstance(self.screen, ModalScreen):
            self.screen.dismiss(None)
            return
        menu = self.query_one("#slash-menu", SlashMenu)
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        if not self._busy:
            menu.set_commands(())
            approval_menu.set_commands(())
            return
        self._pending_question_id = None
        self._pending_question_default = ""
        menu.set_commands(())
        approval_menu.set_commands(())
        self.control_plane.request_cancel("user_cancel")
        self.add_notice("Cancelling…", "warning")
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = False
        prompt.disabled = False
        self._update_composer_hint()
        prompt.focus()

    def action_quit(self) -> None:
        if self._busy:
            self.control_plane.request_cancel("quit")
        if self._agent is not None and self._agent.learning_loop is not None:
            self._agent.learning_loop.cancel()
        self.exit()

    async def on_unmount(self) -> None:
        if self._busy:
            self.control_plane.request_cancel("quit")
        shutdown = getattr(self._agent, "shutdown_learning", None)
        if callable(shutdown):
            await shutdown()

    def _show_question(self, payload: Mapping[str, Any]) -> None:
        request_id = str(payload.get("request_id") or "")
        question = str(payload.get("question") or "")
        choices = [str(choice) for choice in payload.get("choices") or []]
        default = str(payload.get("default") or "")
        kind = str(payload.get("kind") or "")
        if not request_id or not question:
            self.add_notice("The agent sent an invalid question request.", "error")
            return
        self._pending_question_id = request_id
        self._pending_question_default = default
        self._ui_state.phase = "paused"
        self._ui_state.detail = "waiting for user"
        self._update_composer_hint()
        menu = self.query_one(
            "#approval-menu" if kind == "approval" else "#slash-menu",
            SlashMenu,
        )
        menu.set_question(
            question,
            choices,
            default=default,
            kind=kind,
        )
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = kind == "approval"
        prompt.disabled = False
        prompt.value = "" if choices else default
        prompt.cursor_position = len(prompt.value)
        prompt.focus()

    async def _answer_question(self, answer: str) -> None:
        request_id = self._pending_question_id
        if request_id is None:
            return
        self._pending_question_id = None
        self._pending_question_default = ""
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        self.query_one("#approval-menu", SlashMenu).set_commands(())
        await self.control_plane.answer_user(request_id, answer)
        self._ui_state.phase = "thinking"
        self._ui_state.detail = "resuming"
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = False
        prompt.disabled = True
        self._update_composer_hint()


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: bool = True,
) -> None:
    """Load environment configuration and launch the terminal UI."""
    load_dotenv(override=True)
    CodingAgentApp(
        workspace=workspace,
        model_id=model_id,
        session_id=session_id,
        enable_learning=enable_learning,
    ).run()
