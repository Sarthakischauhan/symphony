"""A conversation-first Textual interface for the Symphony coding agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen

from coding_agent.agent import CodingAgent, build_agent
from coding_agent.config import ensure_spawn_settings
from coding_agent.config.credentials import OFFLINE_HINT, load_provider_env
from coding_agent.addons.persistence.active import register_active, release_active
from coding_agent.tui.chrome import ComposerOverlay, StatusBar, TopBar
from coding_agent.tui.commands import CommandManager, model_options
from coding_agent.tui.composer import (
    Composer,
    PromptInput,
    QueuedPrompt,
    QueuedTurn,
    SlashMenu,
)
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
from coding_agent.tui.screens.file_selector import WorkspaceFileIndex
from coding_agent.tui.screens.onboard import OnboardApp
from coding_agent.tui.terminal_title import TerminalTitleSurface
from coding_agent.tui.theme import APP_CSS, SYMPHONY_RICH_THEME
from coding_agent.tui.theme.load import ThemeConfigError, apply_theme, load_theme, theme_signature
from coding_agent.tui.tools import ToolCallSummary, ToolCallWidget
from coding_agent.tui.tools.images import dropped_image_paths
from coding_agent.tui.transcript import (
    AssistantMessage,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    TranscriptScroll,
    TranscriptSurface,
    Welcome,
)
from core_ai import has_configured_provider
from core_harness import Answer, Interrupt, Op


def _paste_might_be_images(text: str) -> bool:
    """True when a paste is short enough to be a file drop naming an image.

    No filesystem access. Ordinary text, including large pastes, fails here
    on length or on a missing image suffix.
    """
    if not text or len(text) > 4096:
        return False
    lowered = text.lower()
    return any(suffix in lowered for suffix in _IMAGE_DROP_SUFFIXES)


_IMAGE_DROP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
)


class CodingAgentApp(
    TranscriptSurface,
    SubagentSurface,
    QuestionSurface,
    ComposerSurface,
    TurnSurface,
    TerminalTitleSurface,
    App[None],
):
    """Full-screen chat transcript backed by core_harness events."""

    CSS = APP_CSS
    # Keep terminal mouse drag selection enabled for transcript content.
    ALLOW_SELECT = True

    BINDINGS = [
        Binding("ctrl+g", "subagents", "Subagents", show=False),
        Binding("ctrl+b", "dashboard", "Agents", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("ctrl+y", "copy_selection", "Copy selection", show=False),
        Binding("ctrl+a", "voice", "Voice", show=False, priority=True),
        Binding("escape", "cancel_voice", "Leave voice", show=False, priority=True),
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
        enable_jev: Optional[bool] = None,
        unattended: bool = False,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.model_id = model_id
        self.session_id = session_id
        self._resumed = session_id is not None
        self.enable_learning = enable_learning
        self.enable_jev = enable_jev
        self.jev_rule = ""
        overrides: dict[str, Any] = {}
        if enable_learning is not None:
            overrides["learning"] = {"enabled": enable_learning}
        if enable_jev is not None:
            overrides["evaluation"] = {"enabled": enable_jev}
        if unattended:
            overrides["unattended"] = True
        self.config = ensure_spawn_settings(
            self.workspace, overrides=overrides or None
        )
        self.sink = TextualEventSink(workspace=self.workspace)
        self._agent: Optional[CodingAgent] = None
        self._busy = False
        self._reload_queued = False
        # Prompts submitted while a turn is running are dispatched FIFO.
        self._queued_turns: list[QueuedTurn] = []
        self._init_runtime_state()

    def queue_turn(self, turn: QueuedTurn) -> None:
        """Add a follow-up prompt and refresh the queue control."""
        self._queued_turns.append(turn)
        self.query_one("#queued-prompt-row", QueuedPrompt).refresh_queue(self._queued_turns)

    def pop_queued_turn(self) -> QueuedTurn:
        """Remove and return the oldest queued prompt."""
        turn = self._queued_turns.pop(0)
        self.query_one("#queued-prompt-row", QueuedPrompt).refresh_queue(self._queued_turns)
        return turn

    def _init_runtime_state(self) -> None:
        self._ui_state = UiRunState()
        self._presenter: Optional[EventPresenter] = None
        self._assistant: Optional[AssistantMessage] = None
        self._thinking: Optional[ThinkingStatus] = None
        self._reasoning: Optional[ReasoningWidget] = None
        self._process: Optional[RunProcess] = None
        self._tools: dict[str, ToolCallWidget] = {}
        self._tool_groups: dict[str, ToolCallSummary] = {}
        self._open_tool_group: Optional[ToolCallSummary] = None
        self._subagents: dict[str, SubagentRecord] = {}
        self._session_artifacts: dict[Path, tuple[str, str, Path]] = {}
        self._file_index = WorkspaceFileIndex(self.workspace)
        self._pending_question_id: str | None = None
        self._pending_question_agent_id = ""
        self._pending_question_default = ""
        self._model_options = model_options()
        self._command_manager = CommandManager(self)
        self._stream_flush_timer = None
        self._run_generation = 0
        self._topbar_model: Optional[str] = None
        self._theme_signature = theme_signature()
        self._theme_timer = None
        self._voice_active = False
        self._voice_timer = None
        self._voice_addon = None
        self._voice_session = None

    async def on_event(self, event: events.Event) -> None:
        # Textual delivers paste only to the focused widget, so a drop on the
        # transcript never reaches the composer. Claim image drops here, before
        # that forward, and leave every other event on the normal path.
        if (
            isinstance(event, events.Paste)
            and not event.is_forwarded
            and self._attach_dropped_images(event.text)
        ):
            return
        await super().on_event(event)

    def _attach_dropped_images(self, text: str) -> bool:
        """Attach a dropped image path when focus is not the composer.

        Returns True only when this paste was consumed. Non-image pastes,
        modal screens, and a focused composer return False with no filesystem
        work beyond the existing path check for a short image-like paste.
        """
        if len(self.screen_stack) != 1 or not _paste_might_be_images(text):
            return False
        paths = dropped_image_paths(text)
        if not paths:
            return False
        try:
            prompt = self.query_one("#prompt", PromptInput)
        except Exception:
            return False
        if prompt.has_focus:
            return False
        for path in paths:
            prompt._attach_image(path)
        return True

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar", background_tasks=self.background_task_count)
        with TranscriptScroll(id="transcript"):
            yield Welcome(self.workspace)
        yield SlashMenu(id="slash-menu")
        yield ComposerOverlay()
        yield Composer(id="composer")
        # Keep approval choices in their own full-width surface.
        yield SlashMenu(id="approval-menu")
        yield StatusBar(id="status")

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
                enable_jev=self.enable_jev,
                config=self.config,
                client="tui",
            )
            from coding_agent.protocols.stdio.commands import load_state

            load_state(self._agent)
            self.sink.fields.bind(self._agent)
        except Exception as exc:
            self._agent = None
            self._set_status("")
            if "explicitly start a fresh session" in str(exc):
                self.add_notice(str(exc), "error")
            elif has_configured_provider():
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
        self.session_id = self._agent.session_id
        persistence = getattr(self._agent, "persistence", None)
        if persistence is not None:
            persistence.client = "tui"
        self._register_active_session()
        topbar.set_context(self.workspace, self._ui_state.model_id)
        self._presenter.refresh_chrome()
        self._theme_timer = self.set_interval(0.5, self._reload_theme_if_changed)
        if self.session_id and self._resumed:
            self.load_session_history()
        self.query_one("#prompt", PromptInput).focus()

    def on_status_bar_cost_breakdown_requested(self, message: StatusBar.CostBreakdownRequested) -> None:
        message.stop()
        self.show_cost_breakdown()

    def show_cost_breakdown(self) -> None:
        """Open the per-model spend for this session, from a click on the cost."""
        from coding_agent.tui.screens.cost import CostBreakdownScreen

        costs = self._ui_state.metrics.model_costs
        if not costs:
            return
        self.push_screen(CostBreakdownScreen(costs))

    def show_artifacts(self) -> None:
        """Open the latest version of each session artifact in a list."""
        from coding_agent.tui.screens.artifacts import ArtifactsScreen

        if self._session_artifacts:
            self.push_screen(ArtifactsScreen(list(self._session_artifacts.values())))

    def show_model_picker(self) -> None:
        """Open the same model list as ``/model``, from a click on the model name."""
        from coding_agent.tui.commands.manager import show_model_picker

        if self._agent is None:
            self.add_notice(OFFLINE_HINT, "error")
            return
        show_model_picker(self)

    def _reload_theme_if_changed(self) -> None:
        """Repaint when ~/.symphony/theme.toml (or the packaged fallback) changes.

        A half-written or invalid file is ignored so a save in progress does
        not blank the running session. The previous theme stays up.
        """
        signature = theme_signature()
        if signature is None or signature == self._theme_signature:
            return
        try:
            document = load_theme()
        except (OSError, ThemeConfigError):
            return
        apply_theme(document)
        self._theme_signature = signature
        # reparse() rereads whatever is already stored. Replace that source
        # first, or an edit to the CSS body never reaches the widgets.
        self.stylesheet.source.clear()
        self.stylesheet.add_source(document.app_css, is_default_css=True)
        self.stylesheet.reparse()
        self.stylesheet.update(self.screen)
        self.refresh(repaint=True, layout=True)
        self._set_status("")

    def submit_op(self, op: Op) -> bool:
        """Send one operation to the agent's harness. True when it landed."""
        submit = getattr(getattr(self._agent, "harness", None), "submit", None)
        if callable(submit):
            return bool(submit(op))
        # No agent yet: a question can still be waiting on the TUI's own port.
        if isinstance(op, Answer):
            return self.sink.interaction.answer(op.request_id, op.value)
        return False

    def _cancel_active_run(self, reason: str) -> None:
        """Stop the agent turn. ``reason`` is reported on ``run_cancelled``."""
        self.sink.request_cancel(reason)
        if self.submit_op(Interrupt(reason)):
            return
        # The worker is outside ``harness.run`` (a slash command, or between
        # turns). Group must match ``run_agent``.
        self.workers.cancel_group(self, "run_agent")
        for worker in list(self.workers):
            if worker.name == "run_agent" and not worker.is_finished:
                worker.cancel()

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
        already = self.sink.cancelled
        self._pending_question_id = None
        self._pending_question_default = ""
        menu.set_commands(())
        approval_menu.set_commands(())
        self._cancel_active_run("user_cancel")
        if not already:
            from coding_agent.tui.chrome.footer import update_banner

            banner = update_banner("cancelling")
            if banner is not None:
                self.add_update(*banner)
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = True
        prompt.disabled = False
        self._update_composer_hint()
        prompt.focus()

    def action_quit(self) -> None:
        if self._busy:
            self._cancel_active_run("quit")
        if self._agent is not None and self._agent.learning_loop is not None:
            self._agent.learning_loop.cancel()
        self.exit()

    def action_voice(self) -> None:
        """Start voice mode, or finish it. Ctrl+A and ``/voice`` both land here."""
        from coding_agent.tui.composer.voice_mode import toggle_voice

        toggle_voice(self)

    def action_cancel_voice(self) -> None:
        """Escape leaves voice mode. When voice is off, cancel the run instead."""
        if not getattr(self, "_voice_active", False):
            self.action_cancel_run()
            return
        from coding_agent.tui.composer.voice_mode import stop_voice

        stop_voice(self, reason="toggled")

    def action_dashboard(self) -> None:
        from coding_agent.tui.screens.dashboard import AgentDashboard

        self.push_screen(AgentDashboard(self._agent.harness if self._agent is not None else None))

    def _register_active_session(self) -> None:
        agent = self._agent
        if agent is None or not agent.session_id:
            return
        register_active(
            agent.session_id,
            workspace=self.workspace,
            kind="tui",
            model_id=getattr(agent.harness, "model_id", "") or "",
        )

    async def on_unmount(self) -> None:
        from coding_agent.tui.composer.voice_mode import close_voice_addon

        if self._voice_session is not None:
            # A listen() still running in a thread worker would hold the mic.
            self._voice_session.capture.close()
        # Exiting: give the audio threads a bounded moment to release the
        # devices instead of leaving them to interpreter shutdown.
        close_voice_addon(self, timeout=2.0)
        release_active()
        harness = getattr(self._agent, "harness", None)
        shutdown_children = getattr(harness, "shutdown_children", None)
        if callable(shutdown_children):
            await shutdown_children()
        if self._busy:
            self._cancel_active_run("quit")
        shutdown = getattr(self._agent, "shutdown_learning", None)
        if callable(shutdown):
            await shutdown()


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: Optional[bool] = None,
    enable_jev: Optional[bool] = None,
    unattended: bool = False,
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
        enable_jev=enable_jev,
        unattended=unattended,
    ).run()
