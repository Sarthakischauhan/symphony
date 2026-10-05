"""Optional Jev critic mode for coding-agent runs."""

from __future__ import annotations

from typing import Any

from coding_agent._lazy import resolve
from coding_agent.evaluation.evaluators import (
    LLMEvaluator,
    MockEvaluator,
    StubEvaluator,
    VercelJevEvaluator,
)
from coding_agent.evaluation.handlers import HandlerResult, dispatch
from coding_agent.evaluation.policy import (
    JEV_SYSTEM_SEGMENT,
    NUDGE_MARKER,
    PolicyDecision,
    apply_findings_gate,
    critic_message,
    decide_next_step,
)
from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationDecision,
    EvaluationFinding,
    EvaluationResult,
    Evaluator,
    FINISH_QUESTIONS,
    START_QUESTIONS,
)
from coding_agent.evaluation.state import RunState, build_run_state, clip_text

_ADDON_EXPORTS = {
    "JevAddon": ("coding_agent.addon.evaluation", "JevAddon"),
    "jev_from_config": ("coding_agent.addon.evaluation", "jev_from_config"),
}

__all__ = [
    "CONTINUE_NORMALLY",
    "EvaluationDecision",
    "EvaluationFinding",
    "EvaluationResult",
    "Evaluator",
    "FINISH_QUESTIONS",
    "HandlerResult",
    "JEV_SYSTEM_SEGMENT",
    "JevAddon",
    "LLMEvaluator",
    "NUDGE_MARKER",
    "PolicyDecision",
    "MockEvaluator",
    "RunState",
    "START_QUESTIONS",
    "StubEvaluator",
    "VercelJevEvaluator",
    "apply_findings_gate",
    "build_run_state",
    "clip_text",
    "critic_message",
    "decide_next_step",
    "dispatch",
    "jev_from_config",
]


def __getattr__(name: str) -> Any:
    return resolve(globals(), name, _ADDON_EXPORTS)
