"""Agent-turn worker mixed into CodingAgentApp."""

from __future__ import annotations

import asyncio
from typing import Callable

from textual import work
from textual.widgets import Static

from coding_agent.tui.chrome import display_workspace_path, footer_hint, render_footer
from coding_agent.tui.composer.input import PromptInput
from coding_agent.tui.runtime.sink import HarnessEvent
from coding_agent.tui.screens.history import load_session_history
from core_ai.types import Content
from core_harness import HarnessCancelled, HarnessLimitExceeded, HarnessResult

STREAM_PAINT_INTERVAL_S = 1 / 15


class TurnSurface:
    """Harness event routing and the exclusive agent-turn worker."""

    def _set_status(self, _value: str) -> None:
        """Repaint the footer from run state; the presenter's text summary is unused."""
        hint = footer_hint(question_pending=self._pending_question_id is not None)
        self.query_one("#status", Static).update(
            render_footer(
                self._ui_state,
                hint=hint,
                workspace=display_workspace_path(self.workspace),
            )
        )

    def _schedule_stream_flush(self, callback: Callable[[], None]) -> None:
        """Coalesce stream paints to keep Markdown/widget work bounded."""
        if getattr(self, "_stream_flush_timer", None) is not None:
            return

        def _run() -> None:
            self._stream_flush_timer = None
            callback()

        self._stream_flush_timer = self.set_timer(STREAM_PAINT_INTERVAL_S, _run)

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
        await self.restore_subagents()

    def on_harness_event(self, message: HarnessEvent) -> None:
        payload = message.payload or {}
        if message.event_type == "agent_spawned":
            self._on_agent_spawned(payload)
            return
        if message.event_type in {"agent_completed", "agent_failed"}:
            self._on_agent_finished(message.event_type, payload)
            return
        if payload.get("parent_id"):
            self._on_child_event(message.event_type, payload)
            if message.event_type == "question_asked":
                self._show_child_question(payload)
            return
        if message.event_type == "question_asked":
            self._show_question(payload)
            return
        if self._presenter is not None:
            self._presenter.handle(message.event_type, payload)
        if self._plan_run_active and message.event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
        }:
            self._plan_run_active = False

    on_control_plane_event = on_harness_event

    @work(exclusive=True, group="run_agent")
    async def run_agent(self, user_input: Content) -> None:
        try:
            await self._run_agent_turn(user_input)
        except (HarnessCancelled, HarnessLimitExceeded, asyncio.CancelledError):
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
        except Exception as exc:  # noqa: BLE001
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
            if self._ui_state.detail != "failed":
                self.add_notice(f"Error · {exc}", "error")
        finally:
            child_question_pending = bool(self._pending_question_id and self._pending_question_agent_id)
            if self._presenter is not None:
                self._ui_state.phase = "paused" if child_question_pending else "idle"
                self._presenter.refresh_chrome()
            self._busy = False
            if not child_question_pending:
                self._pending_question_id = None
                self._pending_question_default = ""
            self.sink.reset_cancel()
            prompt = self.query_one("#prompt", PromptInput)
            if not child_question_pending:
                prompt.submit_on_enter = True
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
