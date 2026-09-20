"""Evaluator protocol, result types, and v1 question sets.

Evaluator methods are named ``on_start`` / ``on_finish`` so they are not
mistaken for missing harness hooks. The add-on maps them onto the existing
``Addon`` surface:

| Evaluator | Addon |
| --- | --- |
| ``on_start`` | ``before_run`` |
| ``on_finish`` | ``after_run`` |

Findings are advisory. v1 may inject one user-role critic note into messages.
It does not map scores onto plan edits, plan mode, or a second harness run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol

DecisionKind = Literal["boolean", "choice", "score", "skipped", "error"]
EvaluationPhase = Literal["start", "finish"]
EvaluationStatus = Literal["ok", "skipped", "error"]

CONTINUE_NORMALLY = "continue_normally"

START_QUESTIONS: dict[str, Any] = {
    "plan_sufficient": {
        "type": "boolean",
        "instructions": "Is the current plan sufficient to complete the request?",
    },
    "needs_replan": {
        "type": "boolean",
        "instructions": "Should the agent replan before taking further action?",
    },
    "next_action": {
        "type": "choice",
        "instructions": (
            "What should the agent do next? Advisory only; Symphony will not auto-act."
        ),
        "criteria": {
            "continue": "Proceed with the current plan",
            "gather": "Gather more information first",
            "replan": "Revise the plan (advisory only)",
            "ask": "Ask the user a clarifying question",
        },
    },
}

FINISH_QUESTIONS: dict[str, Any] = {
    "task_complete": {
        "type": "boolean",
        "instructions": "Did the agent complete the user's request?",
    },
    "remaining_work": {
        "type": "boolean",
        "instructions": "Is there remaining work the agent should still do?",
    },
    "unsupported_claims": {
        "type": "boolean",
        "instructions": (
            "Did the agent make claims unsupported by tool observations or files changed?"
        ),
    },
    "next_action": {
        "type": "choice",
        "instructions": (
            "Recommended next action after this run. Advisory only; choose finish, "
            "continue, retry, or review."
        ),
        "criteria": {
            "finish": "The task is done",
            "continue": "Continue working",
            "retry": "Retry the approach",
            "review": "Human review is needed",
        },
    },
}


@dataclass
class EvaluationDecision:
    """One answered evaluation question."""

    name: str
    kind: DecisionKind
    value: Any = None
    probs: Optional[dict[str, float]] = None
    label: str = ""
    rationale: str = ""


@dataclass
class EvaluationFinding:
    """Structured, non-actuating critic finding."""

    question: str
    kind: DecisionKind
    value: Any = None
    probs: Optional[dict[str, float]] = None
    label: str = ""
    rationale: str = ""


@dataclass
class EvaluationResult:
    """Outcome of ``on_start`` or ``on_finish``."""

    phase: EvaluationPhase
    status: EvaluationStatus = "ok"
    decisions: list[EvaluationDecision] = field(default_factory=list)
    findings: list[EvaluationFinding] = field(default_factory=list)


class Evaluator(Protocol):
    """Critic that inspects a semantic run snapshot. Never the chat model."""

    async def on_start(self, state: Any) -> EvaluationResult:
        """Called from ``JevAddon.before_run``."""

    async def on_finish(self, state: Any) -> EvaluationResult:
        """Called from ``JevAddon.after_run``."""


def findings_from_decisions(decisions: list[EvaluationDecision]) -> list[EvaluationFinding]:
    return [
        EvaluationFinding(
            question=decision.name,
            kind=decision.kind,
            value=decision.value,
            probs=decision.probs,
            label=decision.label,
            rationale=decision.rationale,
        )
        for decision in decisions
    ]


def skipped_result(phase: EvaluationPhase, rationale: str = "") -> EvaluationResult:
    decision = EvaluationDecision(
        name="evaluator",
        kind="skipped",
        label="skipped",
        rationale=rationale,
    )
    return EvaluationResult(
        phase=phase,
        status="skipped",
        decisions=[decision],
        findings=findings_from_decisions([decision]),
    )


def error_result(phase: EvaluationPhase, rationale: str = "") -> EvaluationResult:
    decision = EvaluationDecision(
        name="evaluator",
        kind="error",
        label="error",
        rationale=rationale,
    )
    return EvaluationResult(
        phase=phase,
        status="error",
        decisions=[decision],
        findings=findings_from_decisions([decision]),
    )


def apply_findings_gate(result: EvaluationResult) -> str:
    """Return the code-owned next-step action for this result.

    The mapping lives in ``evaluation.policy`` so thresholds and honour rules
    stay out of the protocol types. Honour/follow-up is off unless configured.
    """
    from coding_agent.evaluation.policy import apply_findings_gate as decide

    return decide(result)


__all__ = [
    "CONTINUE_NORMALLY",
    "DecisionKind",
    "EvaluationDecision",
    "EvaluationFinding",
    "EvaluationPhase",
    "EvaluationResult",
    "EvaluationStatus",
    "Evaluator",
    "FINISH_QUESTIONS",
    "START_QUESTIONS",
    "apply_findings_gate",
    "error_result",
    "findings_from_decisions",
    "skipped_result",
]
