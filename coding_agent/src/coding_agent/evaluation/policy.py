"""Deterministic next-step policy for Jev findings.

Jev is a decision layer, not a chat model. TypeSafe, the AI SDK evaluation
docs, and agent examples such as Foreman all keep this split:

    typed answers + probabilities  ->  code-owned policy  ->  one allowed action

This module is that policy. It never calls the evaluator, never rewrites the
plan file, and never grants extra tools. Default behaviour is a message-only
nudge. Honour/follow-up (a second ``harness.run``) is opt-in and off by default.

Fail-open: skipped/error results, missing answers, and low-confidence booleans
all become ``continue_normally``. Actuation requires an explicit probability
that clears the threshold; a bare ``True`` / label is a weak signal only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from coding_agent.evaluation.protocol import (
    CONTINUE_NORMALLY,
    EvaluationFinding,
    EvaluationResult,
)

NUDGE_MARKER = "Jev critic note:"
_NUDGE_NEXT_ACTIONS = frozenset({"continue", "retry", "replan", "review"})
_FINISH_QUESTIONS = frozenset(
    {"task_complete", "remaining_work", "unsupported_claims"}
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


def should_nudge(findings: Any) -> bool:
    """True when the next model turn should see one critic note.

    Missing probabilities still count as a weak signal. They never clear the
    actuation threshold used by ``decide_next_step``.
    """
    if isinstance(findings, EvaluationResult) and findings.status != "ok":
        return False
    items = _findings_map(findings)
    if _weak_true(items.get("needs_replan")):
        return True
    if _weak_true(items.get("unsupported_claims")):
        return True
    if _weak_true(items.get("task_complete")) and _weak_true(items.get("remaining_work")):
        return True
    action = _choice_label(items.get("next_action"))
    if action not in _NUDGE_NEXT_ACTIONS:
        return False
    if action == "continue":
        return _is_finish_findings(items, findings)
    return True


def format_nudge(findings: Any) -> str:
    """Short template string for one user-role critic note. Not an LLM call."""
    items = _findings_map(findings)
    flagged: list[str] = []
    for name in (
        "needs_replan",
        "unsupported_claims",
        "task_complete",
        "remaining_work",
    ):
        finding = items.get(name)
        if not _weak_true(finding):
            continue
        detail = ((finding.rationale or finding.label) if finding else "").strip()
        flagged.append(f"{name} ({detail})" if detail else name)
    action = _choice_label(items.get("next_action"))
    if action:
        flagged.append(f"next_action={action}")
    flagged_text = ", ".join(flagged) if flagged else "review the latest findings"
    lines = [
        f"{NUDGE_MARKER} plan or outcome looks incomplete.",
        f"Flagged: {flagged_text}.",
    ]
    if action:
        lines.append(f"Suggested next_action: {action}.")
    lines.append("Plan mode was not opened.")
    return "\n".join(lines)


def is_jev_nudge(message: Any) -> bool:
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


def _findings_map(findings: Any) -> dict[str, EvaluationFinding]:
    if findings is None:
        return {}
    if isinstance(findings, EvaluationResult):
        items = findings.findings
    elif isinstance(findings, dict):
        return {
            str(key): value
            for key, value in findings.items()
            if isinstance(value, EvaluationFinding)
        }
    else:
        items = findings
    return {
        finding.question: finding
        for finding in items
        if isinstance(finding, EvaluationFinding)
    }


def _is_finish_findings(items: dict[str, EvaluationFinding], findings: Any) -> bool:
    if isinstance(findings, EvaluationResult):
        return findings.phase == "finish"
    return any(name in items for name in _FINISH_QUESTIONS)


def _choice_label(finding: Optional[EvaluationFinding]) -> str:
    if finding is None:
        return ""
    return str(finding.value or finding.label or "").strip().lower()


def _weak_true(finding: Optional[EvaluationFinding]) -> bool:
    """Label/bool without probs still counts as a weak yes for nudging."""
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
        return fallback
    text = (finding.rationale or finding.label or "").strip()
    return text or fallback


__all__ = [
    "BOOLEAN_ACT_THRESHOLD",
    "MAX_HONOURED_FOLLOW_UPS",
    "NUDGE_MARKER",
    "PolicyAction",
    "PolicyDecision",
    "apply_findings_gate",
    "critic_message",
    "decide_next_step",
    "format_nudge",
    "is_jev_nudge",
    "should_nudge",
]
