"""Jev critic add-on. Evaluates completed runs and suggests revisions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core_ai.types import Message
from core_harness.addons.addon import Addon

from coding_agent.config import EvaluationConfig
from coding_agent.evaluation.evaluators import VercelJevEvaluator
from coding_agent.evaluation.handlers import dispatch
from coding_agent.evaluation.policy import (
    MAX_HONOURED_FOLLOW_UPS,
    PolicyDecision,
    critic_message,
    decide_next_step,
    is_jev_nudge,
)
from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationResult,
    EvaluationPhase,
    Evaluator,
    error_result,
)
from coding_agent.evaluation.state import bound_text, build_run_state
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeState

logger = logging.getLogger(__name__)


class JevAddon(Addon):
    """Evaluate completed runs against the user's rule and task.

    Dispatches named handlers from ``last_decision.action``. Does not override
    ``before_turn`` or ``on_tool`` and never gates tools. A violated user rule
    can trigger one automatic follow-up. It never rewrites the plan file or
    enters plan mode.
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
        self._allowed_tools: Optional[frozenset[str]] = None
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
            (self.config.honour_follow_up or self.config.rule.strip())
            and decision.should_act
            and self.follow_ups >= MAX_HONOURED_FOLLOW_UPS
            and decision.action == "retry"
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
        self._clear_nudge(payload)
        self._queued_nudge = None
        self._allowed_tools = None

    async def after_run(self, **payload: Any) -> None:
        result = payload.get("result")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = getattr(result, "messages", None) or []
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
        self._queued_nudge = self._dispatch(payload, self.last_decision)

    def consume_follow_up(self) -> Optional[str]:
        """Return one revision prompt for a violated rule or opt-in retry."""
        if not (self.config.honour_follow_up or self.config.rule.strip()):
            return None
        decision = self.last_decision
        if decision is None or decision.action != "retry":
            return None
        if not self.config.honour_follow_up and (
            decision.finding is None or decision.finding.question != "rule_satisfied"
        ):
            return None
        if self.follow_ups >= MAX_HONOURED_FOLLOW_UPS:
            return None
        self.follow_ups += 1
        if decision.finding is not None and decision.finding.question == "rule_satisfied":
            return bound_text(
                f"Revise the completed work to satisfy this user rule: {self.config.rule}. "
                f"Jev found: {decision.reason}",
                self.config.request_max_chars,
            )
        return critic_message(decision)

    def _dispatch(
        self,
        payload: dict[str, Any],
        decision: Optional[PolicyDecision],
        *,
        queued: Optional[str] = None,
    ) -> Optional[str]:
        effect = dispatch(decision or PolicyDecision())
        self._allowed_tools = effect.allow
        if effect.note:
            self._apply_nudge(payload, effect.note)
            return effect.note
        if queued:
            self._apply_nudge(payload, queued)
            return queued
        self._clear_nudge(payload)
        return None

    def _message_lists(self, payload: dict[str, Any]) -> list[list[Any]]:
        result = payload.get("result")
        seen: set[int] = set()
        lists: list[list[Any]] = []
        for target in (payload.get("messages"), getattr(result, "messages", None)):
            if not isinstance(target, list) or id(target) in seen:
                continue
            seen.add(id(target))
            lists.append(target)
        return lists

    def _apply_nudge(self, payload: dict[str, Any], note: str) -> None:
        """Write the note onto live messages and ``HarnessResult.messages``."""
        for target in self._message_lists(payload):
            target[:] = [item for item in target if not is_jev_nudge(item)]
            target.append(Message(role="user", content=note))

    def _clear_nudge(self, payload: dict[str, Any]) -> None:
        for target in self._message_lists(payload):
            target[:] = [item for item in target if not is_jev_nudge(item)]


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
