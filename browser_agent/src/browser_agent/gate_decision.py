"""Turn Jev's choice into the operation the loop may run.

Order matters. A third identical action on an unchanged page is blocked
first. An action must name an element on this page (and TYPE_TEXT must have a
string). The page must still be http(s). A confident ``goal_met`` turns a
passive step into DONE. Last, an action below the confidence floor stops.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from browser_agent.models import Decision, Observation
from browser_agent.validate_url import require_http_url

_PASSIVE = frozenset({"WAIT", "SCROLL_DOWN", "SCROLL_UP"})
_TARGETED = frozenset({"CLICK", "TYPE_TEXT", "SELECT", "PRESS_ENTER"})


def repeat_key(decision: Decision, observation: Observation) -> str:
    """Fingerprint of the action and the page it ran on.

    ``type_value`` is the resolved string (Jev's literal or the text writer's),
    before redaction. Only this digest is kept in history, never the string.
    """
    raw = [decision.operation, decision.target_index(), decision.type_value, observation.url, observation.text]
    return hashlib.sha256(json.dumps(raw).encode()).hexdigest()[:16]


def _blocked(decision: Decision, reason: str) -> Decision:
    return decision.model_copy(update={"operation": "BLOCKED", "reason": reason})


def gate(
    decision: Decision,
    observation: Observation,
    history: list[dict[str, Any]],
    *,
    min_confidence: float,
    goal_met_stop: float,
) -> Decision:
    """Return ``decision`` unchanged, promoted to DONE, or turned into BLOCKED with a reason."""
    operation = decision.operation
    if operation in {"DONE", "BLOCKED"}:
        return decision
    recent = [item.get("repeat_key") for item in history[-2:]]
    if operation not in _PASSIVE and recent == [repeat_key(decision, observation)] * 2:
        return _blocked(decision, "The same action was chosen three times in a row without the page changing.")
    if operation in _TARGETED and observation.find(decision.target_index()) is None:
        return _blocked(decision, f"{operation} names no element on this page.")
    if operation == "TYPE_TEXT" and not decision.type_value:
        return _blocked(decision, "TYPE_TEXT was chosen but no string was available.")
    try:
        require_http_url(observation.url)
    except ValueError as exc:
        return _blocked(decision, str(exc))
    if operation in _PASSIVE and decision.goal_met and decision.goal_met_confidence >= goal_met_stop:
        return decision.model_copy(update={"operation": "DONE", "reason": decision.reason or "Goal is visible."})
    if operation not in _PASSIVE and decision.confidence < min_confidence:
        return _blocked(decision, "Stopped because the chosen action was below the confidence floor.")
    return decision


__all__ = ["gate", "repeat_key"]
