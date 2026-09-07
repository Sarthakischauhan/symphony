"""A conversation-first Textual interface for the Symphony coding agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from coding_agent.agent import AgentMode, CodingAgent, build_agent
from coding_agent.config import ensure_spawn_settings
from coding_agent.credentials import OFFLINE_HINT, load_provider_env
from coding_agent.plan import PlanStore
from coding_agent.tui.chrome import TopBar
from coding_agent.tui.commands import CommandManager, model_options
from coding_agent.tui.composer import Composer, PromptInput, SlashMenu
from coding_agent.tui.composer.surface import ComposerSurface
from coding_agent.tui.runtime import (
    EventPresenter,
    SubagentRecord,
    TextualEventSink,
    UiRunState,
)
from coding_agent.tui.runtime.subagent import SubagentSurface
from coding_agent.tui.runtime.turn import TurnSurface
from coding_agent.tui.screens.ask import QuestionSurface
from coding_agent.tui.screens.onboard import OnboardApp
from coding_agent.tui.theme import APP_CSS, SYMPHONY_RICH_THEME
from coding_agent.tui.tools import ToolCallSummary, ToolCallWidget
from coding_agent.tui.transcript import (
    AssistantMessage,
    LIVE_TOOL_WIDGET_LIMIT,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    TranscriptSurface,
    TranscriptTurn,
    Welcome,
)
from core_ai import has_configured_provider


class CodingAgentApp(
    TranscriptSurface,
    SubagentSurface,
    QuestionSurface,
    ComposerSurface,
    TurnSurface,
    App[None],
):
    """Full-screen chat transcript backed by core_harness events."""

    CSS = APP_CSS
    # Keep terminal mouse drag selection enabled for transcript content.
    ALLOW_SELECT = True

    BINDINGS = [
        Binding("ctrl+g", "subagents", "Subagents", show=False),
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
        enable_learning: Optional[bool] = None,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.model_id = model_id
        self.session_id = session_id
        self.enable_learning = enable_learning
        overrides = None
        if enable_learning is not None:
            overrides = {"learning": {"enabled": enable_learning}}
        self.config = ensure_spawn_settings(self.workspace, overrides=overrides)
        self.mode: AgentMode = "build"
        self.sink = TextualEventSink(
            workspace=self.workspace,
            approvals=self.config.approvals,
        )
        self._agent: Optional[CodingAgent] = None
        self._busy = False
        self._ui_state = UiRunState()
        self._presenter: Optional[EventPresenter] = None
        self._assistant: Optional[AssistantMessage] = None
        self._thinking: Optional[ThinkingStatus] = None
        self._reasoning: Optional[ReasoningWidget] = None
        self._process: Optional[RunProcess] = None
        self._transcript_turns: list[TranscriptTurn] = []
        self._current_transcript_turn: Optional[TranscriptTurn] = None
        self._tools: dict[str, ToolCallWidget | ToolCallSummary] = {}
        self._subagents: dict[str, SubagentRecord] = {}
        self._plan_store = PlanStore(self.workspace)
        self._plan_run_active = False
        self._pending_question_id: str | None = None
        self._pending_question_agent_id = ""
        self._pending_question_default = ""
        self._model_options = model_options()
        self._command_manager = CommandManager(self)
        self.live_tool_widget_limit = LIVE_TOOL_WIDGET_LIMIT
        self._scroll_end_scheduled = False
        self._pending_scroll_end = False
        self._stream_flush_timer = None

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with VerticalScroll(id="transcript"):
            yield Welcome(self.workspace)
        yield SlashMenu(id="slash-menu")
        yield Composer(id="composer")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        self.sink.bind(self)
        self._presenter = EventPresenter(
            state=self._ui_state,
            view=self,
            set_status=self._set_status,
            workspace=str(self.workspace),
            schedule_flush=self._schedule_stream_flush,
        )
        topbar = self.query_one("#topbar", TopBar)
        topbar.set_context(self.workspace, self.model_id or os.getenv("OPENAI_MODEL", ""))
        self._update_composer_hint()

        try:
            self._agent = build_agent(
                workspace=self.workspace,
                sink=self.sink,
                model_id=self.model_id,
                session_id=self.session_id,
                enable_learning=self.enable_learning,
                config=self.config,
            )
            self._agent.set_mode(self.mode)
        except Exception as exc:
            self._set_status("")
            if has_configured_provider():
                self.add_notice(f"Offline · {exc}. {OFFLINE_HINT}", "error")
            else:
                self.add_notice(OFFLINE_HINT, "error")
            self.query_one("#prompt", PromptInput).focus()
            return

        self._ui_state.model_id = self._agent.harness.model_id
        self._model_options = model_options(self._agent.registry.namespaces())
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

    def action_cancel_run(self) -> None:
        if isinstance(self.screen, ModalScreen):
            close = getattr(self.screen, "action_close_modal", None)
            if callable(close):
                close()
            else:
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
        self.sink.request_cancel("user_cancel")
        self.workers.cancel_group(self, "run_agent")
        self.add_notice("Cancelling…", "warning")
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = True
        prompt.disabled = False
        self._update_composer_hint()
        prompt.focus()

    def action_quit(self) -> None:
        if self._busy:
            self.sink.request_cancel("quit")
            self.workers.cancel_group(self, "run_agent")
        if self._agent is not None and self._agent.learning_loop is not None:
            self._agent.learning_loop.cancel()
        self.exit()

    async def on_unmount(self) -> None:
        harness = getattr(self._agent, "harness", None)
        shutdown_children = getattr(harness, "shutdown_children", None)
        if callable(shutdown_children):
            await shutdown_children()
        if self._busy:
            self.sink.request_cancel("quit")
            self.workers.cancel_group(self, "run_agent")
        shutdown = getattr(self._agent, "shutdown_learning", None)
        if callable(shutdown):
            await shutdown()


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: Optional[bool] = None,
) -> None:
    """Load environment configuration and launch the terminal UI."""
    workspace = Path(workspace).resolve()
    load_provider_env(workspace)
    if not has_configured_provider():
        OnboardApp(workspace).run()
        load_provider_env(workspace)
    CodingAgentApp(
        workspace=workspace,
        model_id=model_id,
        session_id=session_id,
        enable_learning=enable_learning,
    ).run()
