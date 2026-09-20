"""Jev critic add-on. Evaluates at run start/finish, then optionally nudges."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core_ai.types import Message
from core_harness.addons.addon import Addon

from coding_agent.config import EvaluationConfig
from coding_agent.evaluation.evaluators import VercelJevEvaluator
from coding_agent.evaluation.policy import (
    MAX_HONOURED_FOLLOW_UPS,
    PolicyDecision,
    critic_message,
    decide_next_step,
    format_nudge,
    is_jev_nudge,
    should_nudge,
)
from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationResult,
    EvaluationPhase,
    Evaluator,
    error_result,
)
from coding_agent.evaluation.state import build_run_state
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeState

logger = logging.getLogger(__name__)


class JevAddon(Addon):
    """Call the evaluator at run start and finish.

    Does not override ``before_turn`` or ``on_tool``. Default behaviour injects
    at most one user-role critic note per phase. It never rewrites the plan
    file, never enters plan mode, and never starts a second ``harness.run``
    unless ``evaluation.honour_follow_up`` is on.
    """

    name = "jev"

    def __init__(
        self,
        config: EvaluationConfig,
        *,
        evaluator: Optional[Evaluator] = None,
        plan_store: Optional[PlanStore] = None,
        plan_mode: Optional[PlanModeState] = None,
    ) -> None:
        self.config = config
        self.evaluator = evaluator or VercelJevEvaluator(config)
        self.plan_store = plan_store
        self.plan_mode = plan_mode
        self.last_start: Optional[EvaluationResult] = None
        self.last_finish: Optional[EvaluationResult] = None
        self.last_decision: Optional[PolicyDecision] = None
        self.gated_action = CONTINUE_NORMALLY
        self.follow_ups = 0
        self._queued_nudge: Optional[str] = None
        self._harness: Any = None

    def attach(self, harness: Any) -> None:
        self._harness = harness

    def fork_for_child(self, parent_harness: Any) -> None:
        """Skip inherit: child runs are not evaluated by Jev."""
        del parent_harness
        return None

    def _plan_markdown(self) -> str:
        if self.plan_store is not None:
            return self.plan_store.load()
        if self.plan_mode is None or not self.plan_mode.plan_path:
            return ""
        try:
            return Path(self.plan_mode.plan_path).read_text(encoding="utf-8")
        except OSError:
            return ""

    async def _call(
        self, method_name: str, phase: EvaluationPhase, **state_kwargs: Any
    ) -> EvaluationResult:
        state = build_run_state(config=self.config, phase=phase, **state_kwargs)
        method = getattr(self.evaluator, method_name)
        try:
            result = await method(state)
        except Exception as exc:
            logger.warning("Jev %s failed open: %s", method_name, exc)
            result = error_result(phase, str(exc)[:280])
        decision = decide_next_step(result)
        if (
            self.config.honour_follow_up
            and decision.should_act
            and self.follow_ups >= MAX_HONOURED_FOLLOW_UPS
            and decision.action in {"replan", "retry"}
        ):
            decision = PolicyDecision(
                action=CONTINUE_NORMALLY,
                reason="follow-up budget exhausted",
                finding=decision.finding,
            )
        self.last_decision = decision
        self.gated_action = decision.action
        logger.info(
            "jev %s status=%s findings=%s gate=%s reason=%s",
            phase,
            result.status,
            [finding.question for finding in result.findings],
            self.gated_action,
            decision.reason,
        )
        if self._harness is not None:
            for addon in self._harness.addons:
                hook = getattr(addon, "on_evaluation", None)
                if callable(hook):
                    await hook(phase=phase, result=result, evaluator="jev")
        return result

    async def before_run(self, **payload: Any) -> None:
        messages = payload.get("messages") or []
        self.last_start = await self._call(
            "on_start",
            "start",
            request=payload.get("task") or "",
            messages=messages,
            plan_text=self._plan_markdown(),
        )
        if should_nudge(self.last_start):
            self._inject_nudge(messages, format_nudge(self.last_start))
            self._queued_nudge = None
        elif self._queued_nudge:
            self._inject_nudge(messages, self._queued_nudge)
            self._queued_nudge = None

    async def after_run(self, **payload: Any) -> None:
        result = payload.get("result")
        messages = payload.get("messages") or getattr(result, "messages", None) or []
        tool_calls = getattr(result, "tool_calls", None) or ()
        final = getattr(result, "output_text", None) or ""
        self.last_finish = await self._call(
            "on_finish",
            "finish",
            request=payload.get("task") or "",
            messages=messages,
            plan_text=self._plan_markdown(),
            final=final,
            tool_calls=tool_calls,
        )
        if should_nudge(self.last_finish):
            note = format_nudge(self.last_finish)
            self._inject_nudge(messages, note)
            self._queued_nudge = note
        else:
            self._queued_nudge = None

    def consume_follow_up(self) -> Optional[str]:
        """Return a follow-up user prompt once, or ``None`` to stop.

        Off unless ``evaluation.honour_follow_up`` is explicitly true.
        """
        if not self.config.honour_follow_up:
            return None
        decision = self.last_decision
        if decision is None or decision.action not in {"retry", "replan"}:
            return None
        if self.follow_ups >= MAX_HONOURED_FOLLOW_UPS:
            return None
        self.follow_ups += 1
        return critic_message(decision)

    def _inject_nudge(self, messages: list[Any], note: str) -> None:
        if not isinstance(messages, list):
            return
        messages[:] = [item for item in messages if not is_jev_nudge(item)]
        messages.append(Message(role="user", content=note))


def jev_from_config(
    config: EvaluationConfig,
    *,
    plan_store: Optional[PlanStore] = None,
    plan_mode: Optional[PlanModeState] = None,
    evaluator: Optional[Evaluator] = None,
) -> Optional[JevAddon]:
    """Mount the add-on only when critic mode is enabled."""
    if not config.enabled:
        return None
    return JevAddon(
        config,
        evaluator=evaluator,
        plan_store=plan_store,
        plan_mode=plan_mode,
    )


__all__ = ["JevAddon", "jev_from_config"]
