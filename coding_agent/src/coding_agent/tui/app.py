"""Minimal Textual chat shell for CodingAgent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual import work

from coding_agent.agent import CodingAgent
from coding_agent.tui.control_plane import ControlPlaneEvent, TextualControlPlane


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
    """Basic transcript + input TUI. Streaming polish comes in later phases."""

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
    SUB_TITLE = "minimal TUI"

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status")
        with Vertical():
            yield RichLog(id="log", markup=True, highlight=True, wrap=True)
            yield Input(
                placeholder="Message the coding agent… (Enter to send)",
                id="prompt",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.control_plane.bind(self)
        status = self.query_one("#status", Static)
        log = self.query_one("#log", RichLog)
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

        model = self._agent.harness.model_id
        status.update(f"model={model}  workspace={self.workspace}")
        log.write("[bold]Ready.[/bold] Type a task and press Enter.")
        self.query_one("#prompt", Input).focus()

    def on_control_plane_event(self, message: ControlPlaneEvent) -> None:
        # Minimal scaffold: surface tool lifecycle; final assistant text comes from run().
        log = self.query_one("#log", RichLog)
        et = message.event_type
        payload = message.payload

        if et == "tool_execution_started":
            name = payload.get("tool_name", "tool")
            log.write(f"[cyan]→ {name}[/cyan] {payload.get('arguments', {})}")
            return

        if et == "tool_execution_completed":
            name = payload.get("tool_name", "tool")
            result = str(payload.get("result", ""))
            preview = result if len(result) <= 240 else result[:240] + "…"
            log.write(f"[green]✓ {name}[/green] {preview}")
            return

        if et == "run_started":
            log.write("[dim]— run started —[/dim]")
            return

        if et == "run_completed":
            log.write("[dim]— run completed —[/dim]")
            return

        if et == "run_failed":
            log.write(f"[red]run failed: {payload.get('message', payload)}[/red]")

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
        assert self._agent is not None
        log = self.query_one("#log", RichLog)
        try:
            result = await self._agent.run(user_input)
            if result.output_text:
                log.write(f"[bold]assistant>[/bold] {result.output_text}")
        except Exception as exc:  # noqa: BLE001 — surface run failures in the log
            log.write(f"[red]error: {exc}[/red]")
        finally:
            self._busy = False
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            prompt.focus()


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
