"""A conversation-first Textual interface for the Symphony coding agent."""

from __future__ import annotations

import os
import uuid
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
from coding_agent.tui.commands import (
    MODE_CATALOG,
    MODEL_CATALOG,
    SLASH_COMMANDS,
    PlanOption,
    command_matches,
    find_mode,
    find_model,
    mode_matches,
    model_matches,
)
from coding_agent.tui.control_plane import HarnessEvent, TextualControlPlane
from coding_agent.tui.events import EventPresenter
from coding_agent.tui.agent_factory import build_agent
from coding_agent.tui.history import load_session_history
from coding_agent.tui.state import UiRunState
from coding_agent.tui.status import render_status
from coding_agent.tui.modal import DiffModal, LearningModal, PlanModal
from coding_agent.tui.styles.app import APP_CSS
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
        menu = self.query_one("#slash-menu", SlashMenu)
        if event.value.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(model_matches(event.value.removeprefix("/model ")), current)
        elif event.value.startswith("/mode "):
            menu.set_modes(mode_matches(event.value.removeprefix("/mode ")), self.mode)
        elif event.value.startswith("/plan "):
            menu.set_plans(
                self._plan_options(event.value.removeprefix("/plan ")),
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
                self._toggle_mode()
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
        if command == "learning":
            self._open_learning_modal()
            return
        if command == "plan":
            if argument:
                self._open_plan_modal(argument)
                return
            plans = self._plan_options()
            if not plans:
                self.add_notice("No saved plans yet. Switch to Plan mode to create one.")
                return
            prompt = self.query_one("#prompt", Input)
            prompt.value = "/plan "
            prompt.cursor_position = len(prompt.value)
            self.query_one("#slash-menu", SlashMenu).set_plans(
                plans,
                self._plan_store.path.name,
            )
            return
        if command == "mode":
            if self._busy:
                self.add_notice("/mode is unavailable while a turn is running.", "warning")
                return
            if argument:
                self._select_mode(argument)
            else:
                prompt = self.query_one("#prompt", Input)
                prompt.value = "/mode "
                prompt.cursor_position = len(prompt.value)
                self.query_one("#slash-menu", SlashMenu).set_modes(
                    MODE_CATALOG,
                    self.mode,
                )
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
        if command == "diff":
            self._open_diff_modal()
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

    def _select_mode(self, argument: str) -> None:
        selected = find_mode(argument)
        if selected is None:
            self.add_notice(
                f"Unknown mode: {argument}. Run /mode to see available modes.",
                "warning",
            )
            return
        self.mode = selected.id  # type: ignore[assignment]
        if self._agent is not None:
            self._agent.set_mode(self.mode)
        self._update_composer_hint()
        self.add_notice(f"Switched to {selected.label} mode", "success")

    def _toggle_mode(self) -> None:
        self.mode = "plan" if self.mode == "build" else "build"
        if self._agent is not None:
            self._agent.set_mode(self.mode)
        self._update_composer_hint()

    def _update_composer_hint(self) -> None:
        label = self.mode.upper()
        self.query_one("#composer", Composer).set_class(
            self.mode == "plan", "plan-mode"
        )
        self.query_one("#composer-hint", Static).update(
            f"{label} · Tab mode · Enter to send"
        )

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
            f"mode      {self.mode}\n"
            f"session   {self._agent.session_id}\n"
            f"context   {context}"
        )

    def _open_diff_modal(self) -> None:
        self.push_screen(DiffModal(self.workspace))

    def _open_learning_modal(self) -> None:
        self.push_screen(LearningModal(self.workspace))

    def _plan_options(self, query: str = "") -> tuple[PlanOption, ...]:
        needle = query.strip().lower()
        options: list[PlanOption] = []
        for path in self._plan_store.list_paths():
            task = self._plan_store.task_for(path)
            if needle and needle not in path.name.lower() and needle not in task.lower():
                continue
            options.append(
                PlanOption(
                    id=path.name,
                    label=task,
                    description=str(path.relative_to(self.workspace)),
                )
            )
        return tuple(options)

    def _open_plan_modal(self, plan_name: str | None = None) -> None:
        if plan_name is not None and self._plan_store.select(plan_name) is None:
            self.add_notice(f"Unknown plan: {plan_name}. Run /plan to choose one.", "warning")
            return
        if not self._plan_store.path.exists():
            self.add_notice("No saved plans yet. Switch to Plan mode to create one.")
            return
        self.push_screen(PlanModal(self.workspace), self._on_plan_action)

    def _on_plan_action(self, action: str | None) -> None:
        if action != "build" or self._busy:
            return
        self.mode = "build"
        if self._agent is not None:
            self._agent.set_mode("build")
        self._update_composer_hint()
        prompt = self.query_one("#prompt", Input)
        plan_path = self._plan_store.path.relative_to(self.workspace)
        prompt.value = f"Build the approved plan in {plan_path}."
        prompt.action_submit()

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
            self._open_plan_modal()
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


def run_tui(
    *,
    workspace: str | Path = ".",
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Load environment configuration and launch the terminal UI."""
    load_dotenv(override=True)
    CodingAgentApp(workspace=workspace, model_id=model_id, session_id=session_id).run()
