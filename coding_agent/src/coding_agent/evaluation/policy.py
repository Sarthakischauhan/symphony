"""Deterministic next-step policy for Jev findings.

Jev is a decision layer, not a chat model. TypeSafe, the AI SDK evaluation
docs, and agent examples such as Foreman all keep this split:

    typed answers + probabilities  ->  code-owned policy  ->  one allowed action

This module is that policy. It never calls the evaluator, never rewrites the
plan file, and never grants extra tools. ``JevAddon`` dispatches named
handlers from ``last_decision.action``. Honour/follow-up (a second
``harness.run``) is opt-in and off by default.

Fail-open: skipped/error results, missing answers, and low-confidence booleans
all become ``continue_normally``. Actuation requires an explicit probability
that clears the threshold; a bare ``True`` / label is a weak signal only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationFinding,
    EvaluationResult,
)
from coding_agent.evaluation.state import bound_text

NUDGE_MARKER = "Jev critic note:"
NUDGE_TEXT_LIMIT = 280
JEV_SYSTEM_SEGMENT = (
    "# Jev mode\n"
    f"Treat injected `{NUDGE_MARKER}` as authoritative. "
    "On remaining work, review, or conflicting complete/remaining findings, "
    "continue or fix before claiming the task is done."
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
    2. Finish conflict: ``task_complete`` and ``remaining_work`` both true
       -> ``review``. TypeSafe questions are independent; both-true is invalid.
    3. Explicit ``next_action`` choice, when it belongs to the phase.
    4. High-confidence booleans that imply the same action (start phase;
       finish never actuates on ``task_complete`` or ``remaining_work`` alone).
    5. Otherwise continue.
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


def is_jev_nudge(message: object) -> bool:
    """True when ``message`` is a previously injected Jev critic note."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", "") or part))
        text = "".join(parts)
    else:
        text = str(content or "")
    return NUDGE_MARKER in text


def critic_message(decision: PolicyDecision) -> str:
    """Instruction injected into the conversation so the chat model can act."""
    rationale = _rationale(decision)
    question = decision.finding.question if decision.finding is not None else ""
    if decision.action == "replan":
        body = (
            f"Revise the plan before further implementation. Reason: {rationale} "
            "Do not use write/edit/bash until the plan is revised. Plan mode was not opened."
        )
    elif decision.action == "gather":
        body = (
            f"Gather more information before acting. Reason: {rationale} "
            "Inspect the workspace with read-only tools before making changes."
        )
    elif decision.action == "ask":
        body = (
            f"Ask the user one concrete question with ask_user. Reason: {rationale}"
        )
    elif decision.action == "retry":
        body = (
            f"Finish remaining work from the current workspace. Reason: {rationale}"
        )
    elif decision.action == "review" or question == "unsupported_claims":
        if question == "unsupported_claims":
            body = f"Verify before claiming the task is done. Reason: {rationale}"
        else:
            body = (
                f"Human review is required. Do not claim the task is done. "
                f"Reason: {rationale}"
            )
    else:
        body = rationale
    return bound_text(f"{NUDGE_MARKER} {body}", NUDGE_TEXT_LIMIT) if body else ""


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
    if _boolean_false(findings.get("rule_satisfied")):
        finding = findings["rule_satisfied"]
        return PolicyDecision(action="retry", reason=_rationale_from(finding, "user rule not satisfied"), finding=finding)
    if _weak_true(findings.get("task_complete")) and _weak_true(findings.get("remaining_work")):
        finding = findings.get("remaining_work") or findings.get("task_complete")
        return PolicyDecision(
            action="review",
            reason=_rationale_from(finding, "conflicting finish findings"),
            finding=finding,
        )
    next_action = _choice(findings.get("next_action"), _FINISH_NEXT_ACTIONS)
    if next_action == "review" or _boolean_true(findings.get("unsupported_claims")):
        finding = findings.get("unsupported_claims") if _boolean_true(findings.get("unsupported_claims")) else findings.get("next_action")
        return PolicyDecision(action="review", reason=_rationale_from(finding, "review"), finding=finding)
    if next_action == "retry":
        finding = findings.get("next_action")
        return PolicyDecision(action="retry", reason=_rationale_from(finding, "retry"), finding=finding)
    if next_action == "continue":
        finding = findings.get("next_action")
        return PolicyDecision(action="retry", reason=_rationale_from(finding, "remaining work"), finding=finding)
    if next_action == "finish":
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
    """Return P(true), or -1 when the finding is missing/unusable.

    A bare bool or label is not p=1.0. Actuation needs an explicit probability.
    """
    if finding is None or finding.kind != "boolean":
        return -1.0
    probs = getattr(finding, "probs", None)
    if isinstance(probs, dict) and "true" in probs:
        try:
            return float(probs["true"])
        except (TypeError, ValueError):
            return -1.0
    value = finding.value
    if isinstance(value, bool):
        return -1.0
    if isinstance(value, (int, float)):
        return float(value)
    return -1.0


def _weak_true(finding: Optional[EvaluationFinding]) -> bool:
    """Label/bool without probs still counts as a weak yes for conflict."""
    if finding is None or finding.kind != "boolean":
        return False
    probability = _boolean_probability(finding)
    if probability >= 0.0:
        return probability >= 0.5
    if isinstance(finding.value, bool):
        return finding.value
    label = str(finding.label or "").strip().lower()
    return label in {"true", "yes"}


def _rationale(decision: PolicyDecision) -> str:
    return _rationale_from(decision.finding, decision.reason or decision.action)


def _rationale_from(finding: Optional[EvaluationFinding], fallback: str) -> str:
    if finding is None:
        return bound_text(fallback, NUDGE_TEXT_LIMIT)
    text = (finding.rationale or finding.label or "").strip()
    return bound_text(text or fallback, NUDGE_TEXT_LIMIT)


__all__ = [
    "BOOLEAN_ACT_THRESHOLD",
    "JEV_SYSTEM_SEGMENT",
    "MAX_HONOURED_FOLLOW_UPS",
    "NUDGE_MARKER",
    "NUDGE_TEXT_LIMIT",
    "PolicyAction",
    "PolicyDecision",
    "apply_findings_gate",
    "critic_message",
    "decide_next_step",
    "is_jev_nudge",
]
