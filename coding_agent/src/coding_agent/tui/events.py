"""Map core_harness control-plane events into TUI log/status/live updates."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from rich.markdown import Markdown

from coding_agent.tui.state import UiRunState

WriteFn = Callable[[Any], None]
StatusFn = Callable[[str], None]
LiveFn = Callable[[str], None]


def _preview(value: Any, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


class EventPresenter:
    """Pure presentation logic for harness events (no Textual imports)."""

    def __init__(
        self,
        *,
        state: UiRunState,
        write: WriteFn,
        set_status: StatusFn,
        set_live: LiveFn,
        workspace: str = "",
    ) -> None:
        self.state = state
        self._write = write
        self._set_status = set_status
        self._set_live = set_live
        self.workspace = workspace

    def refresh_chrome(self) -> None:
        self._set_status(self.state.status_line(workspace=self.workspace))
        self._set_live(self.state.live_line())

    def handle(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        payload = payload or {}
        handler = getattr(self, f"_on_{event_type}", None)
        if handler is None:
            self._write(f"[dim]event:{event_type}[/dim] {_preview(payload, 160)}")
            self.refresh_chrome()
            return
        handler(payload)
        self.refresh_chrome()

    def flush_stream_to_log(self) -> None:
        if self.state.stream_started and self.state.stream_text:
            self._write(
                Markdown(
                    f"**assistant>**\n\n{self.state.stream_text}",
                    code_theme="monokai",
                )
            )
            self.state.stream_text = ""
            self.state.stream_started = False

    # --- run lifecycle -------------------------------------------------

    def _on_run_started(self, payload: Dict[str, Any]) -> None:
        model_id = str(payload.get("model_id") or self.state.model_id)
        self.state.reset_for_run(model_id=model_id)
        tools = payload.get("tool_names") or []
        self._write(f"[dim]— run started · tools={list(tools)} —[/dim]")

    def _on_run_completed(self, payload: Dict[str, Any]) -> None:
        self.flush_stream_to_log()
        usage = payload.get("usage") or {}
        context = payload.get("context") or {}
        if usage:
            self.state.update_usage(
                {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "cumulative_tokens": usage.get("total_tokens", 0),
                    "estimated": False,
                }
            )
        if context:
            self.state.update_context(context)
        self.state.phase = "idle"
        self.state.detail = "done"
        self._write("[dim]— run completed —[/dim]")

    def _on_run_failed(self, payload: Dict[str, Any]) -> None:
        self.flush_stream_to_log()
        self.state.phase = "idle"
        self.state.detail = "failed"
        self._write(
            f"[red]run failed ({payload.get('error_type', 'error')}): "
            f"{payload.get('message', payload)}[/red]"
        )

    def _on_run_cancelled(self, payload: Dict[str, Any]) -> None:
        self.flush_stream_to_log()
        self.state.phase = "idle"
        self.state.detail = "cancelled"
        self._write(f"[yellow]run cancelled: {payload.get('reason', 'cancelled')}[/yellow]")

    # --- turns / streaming ("thinking") --------------------------------

    def _on_turn_started(self, payload: Dict[str, Any]) -> None:
        self.flush_stream_to_log()
        turn = int(payload.get("turn") or 0)
        self.state.begin_turn(turn)
        count = payload.get("message_count")
        suffix = f" · messages={count}" if count is not None else ""
        self._write(f"[dim]thinking · turn {turn}{suffix}[/dim]")

    def _on_turn_completed(self, payload: Dict[str, Any]) -> None:
        had_tools = bool(payload.get("had_tool_calls"))
        if not had_tools:
            self.flush_stream_to_log()
        self.state.detail = "turn done"
        if self.state.phase == "streaming":
            self.state.phase = "thinking"

    def _on_text_delta(self, payload: Dict[str, Any]) -> None:
        delta = payload.get("delta") or ""
        if not delta:
            return
        self.state.append_text(str(delta))

    # --- tools ---------------------------------------------------------

    def _on_tool_call_started(self, payload: Dict[str, Any]) -> None:
        self.flush_stream_to_log()
        name = payload.get("tool_name") or "tool"
        self.state.phase = "tool"
        self.state.tool_args_preview = str(name)
        self.state.detail = f"tool {name}"
        self._write(f"[cyan]tool_call {name}[/cyan] id={payload.get('tool_call_id', '')}")

    def _on_tool_call_delta(self, payload: Dict[str, Any]) -> None:
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        self.state.phase = "tool"
        preview = (self.state.tool_args_preview + delta)[-80:]
        self.state.tool_args_preview = preview
        self.state.detail = "tool args"

    def _on_tool_execution_started(self, payload: Dict[str, Any]) -> None:
        name = payload.get("tool_name") or "tool"
        self.state.phase = "tool"
        self.state.detail = f"exec {name}"
        self._write(f"[cyan]→ {name}[/cyan] {_preview(payload.get('arguments', {}))}")

    def _on_tool_execution_completed(self, payload: Dict[str, Any]) -> None:
        name = payload.get("tool_name") or "tool"
        self.state.phase = "thinking"
        self.state.detail = f"done {name}"
        self._write(f"[green]✓ {name}[/green] {_preview(payload.get('result', ''))}")

    # --- metrics -------------------------------------------------------

    def _on_usage(self, payload: Dict[str, Any]) -> None:
        self.state.update_usage(payload)
        est = " ~" if payload.get("estimated") else ""
        self._write(
            f"[dim]usage{est} turn={payload.get('turn')} "
            f"prompt={payload.get('prompt_tokens', 0)} "
            f"completion={payload.get('completion_tokens', 0)} "
            f"total={payload.get('total_tokens', 0)} "
            f"cumulative={payload.get('cumulative_tokens', 0)}[/dim]"
        )

    def _on_context(self, payload: Dict[str, Any]) -> None:
        self.state.update_context(payload)
        left = payload.get("context_left")
        limit = payload.get("context_limit")
        used = payload.get("tokens_used")
        util = payload.get("utilization")
        util_s = f" util={util:.1%}" if isinstance(util, (int, float)) else ""
        self._write(
            f"[dim]context turn={payload.get('turn')} "
            f"used={used} left={left}/{limit}{util_s}[/dim]"
        )

    def _on_context_warning(self, payload: Dict[str, Any]) -> None:
        self._write(
            f"[yellow]context warning: left={payload.get('context_left')} "
            f"threshold={payload.get('threshold')}[/yellow]"
        )

    def _on_compaction_started(self, payload: Dict[str, Any]) -> None:
        self.state.detail = "compacting"
        self._write(
            f"[magenta]compaction started · messages={payload.get('message_count')} "
            f"left={payload.get('context_left')}[/magenta]"
        )

    def _on_compaction_completed(self, payload: Dict[str, Any]) -> None:
        self._write(
            f"[magenta]compaction done · "
            f"{payload.get('message_count_before')}→{payload.get('message_count_after')} msgs · "
            f"~{payload.get('estimated_tokens_before')}→"
            f"{payload.get('estimated_tokens_after')} tokens[/magenta]"
        )

    # --- inbound control -----------------------------------------------

    def _on_paused(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "paused"
        self.state.detail = f"turn {payload.get('turn')}"
        self._write("[yellow]paused[/yellow]")

    def _on_resumed(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "thinking"
        self.state.detail = f"turn {payload.get('turn')}"
        self._write("[dim]resumed[/dim]")

    def _on_message_injected(self, payload: Dict[str, Any]) -> None:
        role = payload.get("role", "user")
        content = _preview(payload.get("content", ""), 200)
        self._write(f"[blue]injected {role}>[/blue] {content}")
