"""Textual chat shell for CodingAgent — driven by core_harness CP events."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from coding_agent.agent import CodingAgent
from coding_agent.tui.control_plane import HarnessEvent, TextualControlPlane
from coding_agent.tui.events import EventPresenter
from coding_agent.tui.state import UiRunState
from core_harness import HarnessResult


def _build_agent(
    *,
    workspace: Path,
    control_plane: TextualControlPlane,
    model_id: Optional[str] = None,
) -> CodingAgent:
    from core_ai import ModelRegistry
    from core_ai.providers.openai import OpenAIProvider

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it (and optionally OPENAI_BASE_URL / "
            "OPENAI_MODEL) before launching the TUI."
        )

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = model_id or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if ":" not in model_name:
        model_name = f"openai:{model_name}"

    registry = ModelRegistry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))
    return CodingAgent(
        registry=registry,
        model_id=model_name,
        workspace=workspace,
        control_plane=control_plane,
    )


class CodingAgentApp(App[None]):
    """Transcript + live stream + metrics, fed by the harness control plane."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
    }

    #log {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }

    #live {
        height: auto;
        min-height: 1;
        max-height: 8;
        padding: 0 1;
        color: $text;
        background: $surface;
    }

    #prompt {
        dock: bottom;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    TITLE = "Symphony Coding Agent"
    SUB_TITLE = "harness events"

    def __init__(
        self,
        *,
        workspace: str | Path = ".workspace",
        model_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.model_id = model_id
        self.control_plane = TextualControlPlane()
        self._agent: Optional[CodingAgent] = None
        self._busy = False
        self._ui_state = UiRunState()
        self._presenter: Optional[EventPresenter] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status")
        with Vertical():
            yield RichLog(id="log", markup=True, highlight=True, wrap=True)
            yield Static(id="live")
            yield Input(
                placeholder="Message the coding agent… (Enter to send)",
                id="prompt",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.control_plane.bind(self)
        status = self.query_one("#status", Static)
        log = self.query_one("#log", RichLog)
        live = self.query_one("#live", Static)

        self._presenter = EventPresenter(
            state=self._ui_state,
            write=log.write,
            set_status=status.update,
            set_live=live.update,
            workspace=str(self.workspace),
        )

        try:
            self._agent = _build_agent(
                workspace=self.workspace,
                control_plane=self.control_plane,
                model_id=self.model_id,
            )
        except Exception as exc:  # noqa: BLE001 — show setup errors in-UI
            status.update(f"offline · {exc}")
            log.write(f"[red]{exc}[/red]")
            log.write("Fix env, then restart. UI scaffold still loads without a live run.")
            return

        self._ui_state.model_id = self._agent.harness.model_id
        self._ui_state.phase = "idle"
        self._ui_state.detail = "ready"
        self._presenter.refresh_chrome()
        log.write("[bold]Ready.[/bold] Type a task and press Enter.")
        log.write("[dim]UI mirrors core_harness control-plane events (stream, tools, usage, context).[/dim]")
        self.query_one("#prompt", Input).focus()

    def on_harness_event(self, message: HarnessEvent) -> None:
        if self._presenter is None:
            return
        self._presenter.handle(message.event_type, message.payload)

    # Textual resolves on_<MessageClass> in snake_case; keep alias for renamed message.
    on_control_plane_event = on_harness_event

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        if not text:
            return
        if self._agent is None:
            self.query_one("#log", RichLog).write("[red]Agent not configured.[/red]")
            return
        if self._busy:
            self.query_one("#log", RichLog).write("[yellow]Busy — wait for the current run.[/yellow]")
            return

        log = self.query_one("#log", RichLog)
        log.write(f"[bold blue]you>[/bold blue] {text}")
        self._busy = True
        event.input.disabled = True
        self.run_agent(text)

    @work(exclusive=True)
    async def run_agent(self, user_input: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            await self._run_agent_turn(user_input)
            # Final assistant text is streamed via text_delta / flushed on turn/run end.
        except Exception as exc:  # noqa: BLE001 — surface run failures in the log
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
            log.write(f"[red]error: {exc}[/red]")
        finally:
            if self._presenter is not None:
                self._ui_state.phase = "idle"
                self._presenter.refresh_chrome()
            self._busy = False
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            prompt.focus()

    async def _run_agent_turn(self, user_input: str) -> HarnessResult:
        assert self._agent is not None
        # Conversation continuity comes from harness persistence + session_id.
        return await self._agent.run(user_input)


def run_tui(
    *,
    workspace: str | Path = ".workspace",
    model_id: Optional[str] = None,
) -> None:
    """Load env and launch the Textual app (blocking)."""
    load_dotenv(override=True)
    workspace_path = Path(
        workspace if workspace != ".workspace" else os.getenv("CODING_AGENT_WORKSPACE", ".workspace")
    )
    app = CodingAgentApp(workspace=workspace_path, model_id=model_id)
    app.run()
