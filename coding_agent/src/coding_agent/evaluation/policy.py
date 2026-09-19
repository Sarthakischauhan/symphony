"""Deterministic next-step policy for Jev findings.

Jev is a decision layer, not a chat model. TypeSafe, the AI SDK evaluation
docs, and agent examples such as Foreman all keep this split:

    typed answers + probabilities  ->  code-owned policy  ->  one allowed action

This module is that policy. It never calls the evaluator, never rewrites the
plan file, and never grants extra tools. It only maps structured findings onto
a small set of harness actions the add-on can honour.

Fail-open: skipped/error results, missing answers, and low-confidence booleans
all become ``continue_normally``. High-impact actions require an explicit
boolean/choice from the current question set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationFinding,
    EvaluationResult,
)

# Actions the add-on is allowed to honour. Anything else is treated as continue.
PolicyAction = Literal[
    "continue_normally",
    "replan",
    "gather",
    "ask",
    "retry",
    "review",
]

# Boolean P(true) must clear this before we treat it as a yes. Matches the
# AI SDK guidance that 0.5 is not a safe auto-action threshold.
BOOLEAN_ACT_THRESHOLD = 0.8

# Cap follow-up runs so a noisy evaluator cannot loop the agent forever.
MAX_HONOURED_FOLLOW_UPS = 1

_START_NEXT_ACTIONS = {"continue", "gather", "replan", "ask"}
_FINISH_NEXT_ACTIONS = {"finish", "continue", "retry", "review"}


@dataclass(frozen=True)
class PolicyDecision:
    """One allowed next step derived from an evaluation result."""

    action: PolicyAction = CONTINUE_NORMALLY
    reason: str = ""
    finding: Optional[EvaluationFinding] = None

    @property
    def should_act(self) -> bool:
        return self.action != CONTINUE_NORMALLY


def apply_findings_gate(result: EvaluationResult) -> str:
    """Return the policy action name. Kept as a stable string API."""
    return decide_next_step(result).action


def decide_next_step(result: EvaluationResult) -> PolicyDecision:
    """Map Jev findings onto one next step.

    Precedence is intentional and conservative:

    1. Evaluator failure / skip -> continue (fail open).
    2. Explicit ``next_action`` choice, when it belongs to the phase.
    3. High-confidence booleans that imply the same action.
    4. Otherwise continue.
    """
    if result.status != "ok":
        return PolicyDecision(
            action=CONTINUE_NORMALLY,
            reason=f"evaluator {result.status}; fail open",
        )
    findings = {finding.question: finding for finding in result.findings}
    if result.phase == "start":
        return _decide_start(findings)
    if result.phase == "finish":
        return _decide_finish(findings)
    return PolicyDecision(reason="unknown evaluation phase")


def critic_message(decision: PolicyDecision) -> str:
    """Instruction injected into the conversation so the chat model can act."""
    rationale = _rationale(decision)
    if decision.action == "replan":
        return (
            "Jev requested a replan before further implementation.\n"
            f"Reason: {rationale}\n"
            "Do not continue coding against the current plan. Revise the plan "
            "first, then wait for approval."
        )
    if decision.action == "gather":
        return (
            "Jev requested more information before acting.\n"
            f"Reason: {rationale}\n"
            "Inspect the workspace with read-only tools before making changes."
        )
    if decision.action == "ask":
        return (
            "Jev requested a clarifying question before continuing.\n"
            f"Reason: {rationale}\n"
            "Ask the user one concrete question with ask_user instead of guessing."
        )
    if decision.action == "retry":
        return (
            "Jev requested another pass on this task.\n"
            f"Reason: {rationale}\n"
            "Continue from the current workspace and finish the remaining work."
        )
    if decision.action == "review":
        return (
            "Jev requested human review before treating this run as complete.\n"
            f"Reason: {rationale}"
        )
    return rationale


def _decide_start(findings: dict[str, EvaluationFinding]) -> PolicyDecision:
    next_action = _choice(findings.get("next_action"), _START_NEXT_ACTIONS)
    if next_action == "replan" or _boolean_true(findings.get("needs_replan")):
        finding = findings.get("needs_replan") if _boolean_true(findings.get("needs_replan")) else findings.get("next_action")
        return PolicyDecision(action="replan", reason=_rationale_from(finding, "replan"), finding=finding)
    if next_action == "ask":
        finding = findings.get("next_action")
        return PolicyDecision(action="ask", reason=_rationale_from(finding, "ask"), finding=finding)
    if next_action == "gather":
        finding = findings.get("next_action")
        return PolicyDecision(action="gather", reason=_rationale_from(finding, "gather"), finding=finding)
    if next_action in {"continue", None} and _boolean_false(findings.get("plan_sufficient")):
        finding = findings.get("plan_sufficient")
        return PolicyDecision(action="replan", reason=_rationale_from(finding, "insufficient plan"), finding=finding)
    return PolicyDecision(reason="start findings do not require a control action")


def _decide_finish(findings: dict[str, EvaluationFinding]) -> PolicyDecision:
    next_action = _choice(findings.get("next_action"), _FINISH_NEXT_ACTIONS)
    if next_action == "review" or _boolean_true(findings.get("unsupported_claims")):
        finding = findings.get("unsupported_claims") if _boolean_true(findings.get("unsupported_claims")) else findings.get("next_action")
        return PolicyDecision(action="review", reason=_rationale_from(finding, "review"), finding=finding)
    if next_action == "retry":
        finding = findings.get("next_action")
        return PolicyDecision(action="retry", reason=_rationale_from(finding, "retry"), finding=finding)
    if next_action == "continue" or _boolean_true(findings.get("remaining_work")):
        finding = findings.get("remaining_work") if _boolean_true(findings.get("remaining_work")) else findings.get("next_action")
        return PolicyDecision(action="retry", reason=_rationale_from(finding, "remaining work"), finding=finding)
    if next_action == "finish" or _boolean_true(findings.get("task_complete")):
        return PolicyDecision(reason="finish findings allow the run to complete")
    return PolicyDecision(reason="finish findings do not require a control action")


def _choice(finding: Optional[EvaluationFinding], allowed: set[str]) -> Optional[str]:
    if finding is None or finding.kind != "choice":
        return None
    value = str(finding.value or finding.label or "").strip().lower()
    if value in allowed:
        return value
    return None


def _boolean_true(finding: Optional[EvaluationFinding]) -> bool:
    return _boolean_probability(finding) >= BOOLEAN_ACT_THRESHOLD


def _boolean_false(finding: Optional[EvaluationFinding]) -> bool:
    probability = _boolean_probability(finding)
    return probability >= 0.0 and probability <= (1.0 - BOOLEAN_ACT_THRESHOLD)


def _boolean_probability(finding: Optional[EvaluationFinding]) -> float:
    """Return P(true), or -1 when the finding is missing/unusable."""
    if finding is None or finding.kind != "boolean":
        return -1.0
    if isinstance(finding.value, bool):
        return 1.0 if finding.value else 0.0
    if isinstance(finding.value, (int, float)):
        return float(finding.value)
    label = str(finding.label or "").strip().lower()
    if label in {"true", "yes"}:
        return 1.0
    if label in {"false", "no"}:
        return 0.0
    return -1.0


def _rationale(decision: PolicyDecision) -> str:
    return _rationale_from(decision.finding, decision.reason or decision.action)


def _rationale_from(finding: Optional[EvaluationFinding], fallback: str) -> str:
    if finding is None:
        return fallback
    text = (finding.rationale or finding.label or "").strip()
    return text or fallback


__all__ = [
    "BOOLEAN_ACT_THRESHOLD",
    "MAX_HONOURED_FOLLOW_UPS",
    "PolicyAction",
    "PolicyDecision",
    "apply_findings_gate",
    "critic_message",
    "decide_next_step",
]
