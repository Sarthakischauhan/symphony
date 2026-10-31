"""Agent-turn worker mixed into CodingAgentApp."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

from textual import work

from coding_agent.tui.chrome import TopBar, display_workspace_path, footer_hint, render_footer
from coding_agent.tui.composer.input import PromptInput
from coding_agent.tui.runtime.sink import HarnessEvent
from coding_agent.tui.screens.history import load_session_history
from core_ai.types import Content
from core_harness import HarnessCancelled, HarnessLimitExceeded, HarnessResult

STREAM_PAINT_INTERVAL_S = 1 / 15


class TurnSurface:
    """Harness event routing and the exclusive agent-turn worker."""

    def _set_status(self, _value: str) -> None:
        """Repaint the footer from run state; the header only when the model changes.

        Usage events refresh this often. Re-reading git and rebuilding the
        top bar on every token made the composer stutter during a live run.
        """
        hint = footer_hint(
            question_pending=self._pending_question_id is not None,
            metrics=self._ui_state.metrics,
        )
        self.query_one("#status").update(
            render_footer(
                self._ui_state,
                hint=hint,
                workspace=display_workspace_path(self.workspace),
            ),
            # The footer has fixed width/height; metrics only change its paint.
            layout=False,
        )
        model_id = self._ui_state.model_id or getattr(self, "model_id", "") or ""
        if model_id != getattr(self, "_topbar_model", None):
            self._topbar_model = model_id
            self.query_one("#topbar", TopBar).set_context(self.workspace, model_id)

    def _schedule_stream_flush(self, callback: Callable[[], None]) -> None:
        """Coalesce stream paints to keep Markdown/widget work bounded."""
        # A structural event can drain paints before this timer fires. Keep
        # the newest generation's callback rather than stranding its updates.
        self._stream_flush_callback = callback
        if getattr(self, "_stream_flush_timer", None) is not None:
            return

        def _run() -> None:
            self._stream_flush_timer = None
            pending = self._stream_flush_callback
            self._stream_flush_callback = None
            if pending is not None:
                pending()

        self._stream_flush_timer = self.set_timer(STREAM_PAINT_INTERVAL_S, _run)

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None:
        """Restore context usage for a resumed session before its first run."""
        metrics = self._ui_state.metrics
        metrics.tokens_used = tokens_used
        metrics.context_limit = context_limit
        metrics.context_left = max(context_limit - tokens_used, 0)
        metrics.utilization = tokens_used / context_limit if context_limit else None
        self._set_status("")

    def set_session_cost(self, costs: dict[str, float]) -> None:
        """Restore the session price so the footer shows it before the next run."""
        metrics = self._ui_state.metrics
        metrics.model_costs = dict(costs)
        metrics.session_cost = sum(costs.values())
        if costs:
            metrics.priced_model = next(reversed(costs))
        self._set_status("")

    @work(exclusive=False)
    async def load_session_history(self) -> None:
        if self._agent is None:
            return
        await load_session_history(self._agent, self)
        await self.restore_subagents()

    def _collect_run_events(self, payload: Mapping[str, Any]) -> None:
        """Tag mid-run journal events as collected after the final output."""
        agent = getattr(self, "_agent", None)
        store = getattr(agent, "persistence", None)
        collect = getattr(store, "collect_run_events", None)
        if not callable(collect):
            return
        session_id = str(
            payload.get("session_id") or getattr(agent, "session_id", "") or ""
        )
        run_id = str(payload.get("run_id") or "")
        if not session_id:
            return

        async def _persist() -> None:
            annotate = getattr(store, "annotate_run_completed", None)
            if callable(annotate):
                elapsed = payload.get("elapsed_seconds")
                await annotate(
                    session_id=session_id,
                    run_id=run_id,
                    completion_verb=str(payload.get("completion_verb") or ""),
                    duration=str(payload.get("duration") or ""),
                    elapsed_seconds=float(elapsed) if isinstance(elapsed, (int, float)) else None,
                )
            await collect(session_id=session_id, run_id=run_id or None)

        self.run_worker(_persist, exclusive=False, group="collect_run_events")

    def feed_voice(self, text: str) -> None:
        from coding_agent.tui.composer.voice_mode import feed_voice

        feed_voice(self, text)

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
        if message.event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
            "run_limit_exceeded",
            "tool_execution_completed",
            "message_injected",
            "waiting_for_children",
        }:
            self._refresh_background_tasks()
        if message.event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
            "run_limit_exceeded",
        }:
            self._collect_run_events(payload)

    def _refresh_background_tasks(self) -> None:
        """Count live background jobs and subagents for the top bar."""
        harness = getattr(self._agent, "harness", None)
        tasks = getattr(harness, "child_tasks", {})
        count = sum(
            1
            for record in tasks.values()
            if getattr(record, "status", "") in {"running", "background"}
            and (getattr(record, "task", None) is None or not record.task.done())
        )
        topbar = self.query_one("#topbar", TopBar)
        topbar.set_background_tasks(count)

    on_control_plane_event = on_harness_event

    @work(exclusive=True, group="run_agent")
    async def run_agent(self, user_input: Content) -> None:
        generation = self._run_generation
        try:
            await self._run_agent_turn(user_input)
        except (HarnessCancelled, HarnessLimitExceeded, asyncio.CancelledError):
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
        except Exception as exc:  # noqa: BLE001
            if self._presenter is not None:
                self._presenter.flush_stream_to_log()
            # run_failed already raised the composer banner. Anything else
            # that escaped the harness, including SSL, uses that same banner.
            if self._ui_state.detail != "failed" and self._presenter is not None:
                self._presenter._show_banner("run_failed", {"message": str(exc)})
        finally:
            if generation != self._run_generation:
                # A newer turn already started; do not clobber its busy state
                # or dispatch the queue a second time.
                return
            child_question_pending = bool(
                self._pending_question_id and self._pending_question_agent_id
            )
            cancel_reason = self.sink.cancel_reason if self.sink.cancelled else None
            dispatch_queued = (
                not child_question_pending
                and bool(self._queued_turns)
                and cancel_reason not in {"user_cancel", "quit"}
            )
            if dispatch_queued:
                # Skip the idle chrome/focus pass — it forced a full layout
                # immediately before the next turn mounted more widgets.
                self.call_after_refresh(self._start_turn, self.pop_queued_turn())
                return
            if self._presenter is not None:
                self._ui_state.phase = "paused" if child_question_pending else "idle"
                self._presenter.refresh_chrome()
            self._busy = False
            if self._reload_queued:
                from coding_agent.tui.commands.manager import reload_project

                self._reload_queued = False
                self.run_worker(reload_project(self), exclusive=False)
            if not child_question_pending:
                self._pending_question_id = None
                self._pending_question_default = ""
            self.sink.reset_cancel()
            voice_addon = getattr(self, "_voice_addon", None)
            if getattr(voice_addon, "_armed", False):
                # Failed/cancelled runs do not reach the harness after_run hook.
                from coding_agent.tui.composer.voice_mode import close_voice_addon

                close_voice_addon(self)
            if getattr(self, "_voice_active", False):
                # The composer is hidden. Leave focus alone until voice mode ends.
                return
            prompt = self.query_one("#prompt", PromptInput)
            if not child_question_pending:
                prompt.submit_on_enter = True
            prompt.disabled = False
            self._update_composer_hint()
            prompt.focus()

    async def _run_agent_turn(self, user_input: Content) -> HarnessResult:
        assert self._agent is not None
        result = await self._agent.run(user_input)
        return result
