"""Reduce Jev's answers to one Decision. Code, not Jev, decides what is runnable."""

from __future__ import annotations

from typing import Any, Optional

from browser_agent.models import Decision


class DecisionError(RuntimeError):
    """Jev is unreachable, misconfigured, or answered with nothing usable."""


def _confidence(answer: dict[str, Any], choice: str) -> tuple[float, dict[str, float]]:
    raw = answer.get("probabilities")
    probabilities = {
        str(key): float(value)
        for key, value in (raw.items() if isinstance(raw, dict) else ())
        if isinstance(value, (int, float))
    }
    if choice in probabilities:
        return probabilities[choice], probabilities
    for key in ("confidence", "probability"):
        value = answer.get(key)
        if isinstance(value, (int, float)):
            return float(value), probabilities
    if probabilities:
        return max(probabilities.values()), probabilities
    # A bare choice is still a decision. Missing calibration must not look
    # like a near-zero confidence refusal.
    return 1.0, probabilities


def _bool_confidence(answer: object) -> tuple[bool, float]:
    if not isinstance(answer, dict):
        return False, 0.0
    probability = answer.get("noul") if answer.get("type") == "noul" else answer.get("probability")
    if isinstance(probability, (int, float)):
        return float(probability) >= 0.5, float(probability)
    chosen = bool(answer.get("value"))
    return chosen, 1.0 if chosen else 0.0


def _choice(answers: dict[str, Any], name: str) -> tuple[str, float, dict[str, float]]:
    answer = answers.get(name)
    if not isinstance(answer, dict):
        return "", 0.0, {}
    choice = str(answer.get("choice") or "").strip()
    return (choice, *_confidence(answer, choice))


def _index(raw: str) -> Optional[int]:
    head = raw.split(":", 1)[0].strip()
    return int(head) if head.isdigit() else None


def decision_from_answers(
    answers: object,
    *,
    model: str,
    provider: str,
    offered_operations: set[str],
) -> Decision:
    """Build the Decision from an ``answers`` object. An unoffered operation becomes BLOCKED."""
    if not isinstance(answers, dict) or not answers:
        raise DecisionError("evaluation model returned no answers")
    operation, confidence, probabilities = _choice(answers, "operation")
    reason = ""
    if operation not in offered_operations:
        operation, confidence = "BLOCKED", 0.0
        reason = "Jev chose an operation that is not available on this page."
    type_value = _choice(answers, "type_value")[0]
    select_raw = _choice(answers, "select_target")[0]
    goal_met, goal_confidence = _bool_confidence(answers.get("goal_met"))
    return Decision(
        operation=operation,
        confidence=confidence,
        click_target=_index(_choice(answers, "click_target")[0]),
        type_target=_index(_choice(answers, "type_target")[0]),
        type_value="" if type_value == "none" else type_value,
        select_index=_index(select_raw),
        select_option=select_raw.split(":", 1)[1] if ":" in select_raw else "",
        goal_met=goal_met,
        goal_met_confidence=goal_confidence,
        model=model,
        provider=provider,
        probabilities=probabilities,
        reason=reason,
    )


__all__ = ["DecisionError", "decision_from_answers"]
