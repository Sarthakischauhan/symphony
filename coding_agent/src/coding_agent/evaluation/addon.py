"""Findings-only Jev critic. Implements Addon ``before_run`` and ``after_run`` only."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core_harness.addons.addon import Addon

from coding_agent.config import EvaluationConfig
from coding_agent.evaluation.evaluators import VercelJevEvaluator
from coding_agent.evaluation.protocol import (
    EvaluationResult,
    EvaluationPhase,
    Evaluator,
    apply_findings_gate,
    error_result,
)
from coding_agent.evaluation.state import build_run_state
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeState

logger = logging.getLogger(__name__)


class JevAddon(Addon):
    """Call the evaluator once at run start and once at run finish.

    Does not override ``before_turn`` or ``on_tool``. Findings are stored on
    the add-on; scores never rewrite the plan.
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
        self.gated_action = "continue_normally"
        self._harness: Any = None

    def attach(self, harness: Any) -> None:
        self._harness = harness

    def fork_for_child(self, parent_harness: Any) -> None:
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
        self.gated_action = apply_findings_gate(result)
        logger.info(
            "jev %s status=%s findings=%s gate=%s",
            phase,
            result.status,
            [finding.question for finding in result.findings],
            self.gated_action,
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
