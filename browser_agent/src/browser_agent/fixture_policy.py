"""Deterministic stand-in so the browser loop can be demoed without a Jev key.

It is not an evaluation model. ``symphony-browser`` uses it only when no Jev
credential is configured, and every event records ``provider=fixture``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from browser_agent.models import Decision, Element, Observation
from browser_agent.rank_elements import goal_tokens, rank_by_goal

_PRICE = re.compile(r"\$\s?\d")


def _goal_satisfied(goal: str, text: str) -> bool:
    """Offline stop condition: a wanted price is visible, or the goal's keywords are."""
    lowered = text.lower()
    wants_price = "price" in goal.lower() or "$" in goal
    if wants_price and not _PRICE.search(text):
        return False
    keywords = goal_tokens(goal, min_length=4)
    if keywords and not any(token in lowered for token in keywords):
        return False
    return wants_price or (bool(keywords) and all(token in lowered for token in keywords[:3]))


def _preferred_field(fields: list[Element]) -> Element:
    pattern = re.compile(r"search|query|q\b|email|destination|from|to", re.IGNORECASE)
    return next((field for field in fields if pattern.search(field.name)), fields[0])


def _submit_button(elements: list[Element]) -> Optional[Element]:
    pattern = re.compile(r"search|go|submit|find|next|continue", re.IGNORECASE)
    return next((e for e in elements if e.kind == "click" and pattern.search(e.name)), None)


class FixturePolicy:
    """Type a goal string, submit, click the best-matching control, scroll, then give up."""

    name = "fixture"
    provider = "fixture"

    async def choose(
        self,
        *,
        goal: str,
        observation: Observation,
        history: list[dict[str, Any]],
        candidates: list[str],
    ) -> Decision:
        """Pick the next step from page contents alone."""
        stamp = {"model": self.name, "provider": self.provider}
        if _goal_satisfied(goal, observation.text):
            reason = "The requested fact is visible on the page."
            met = {"goal_met": True, "goal_met_confidence": 0.99, "reason": reason}
            return Decision(operation="DONE", confidence=0.99, **met, **stamp)
        typables = [element for element in observation.elements if element.kind == "type"]
        if typables and candidates:
            field = _preferred_field(typables)
            if field.value.strip() != candidates[0]:
                typed = {"type_target": field.index, "type_value": candidates[0]}
                return Decision(operation="TYPE_TEXT", confidence=0.9, **typed, **stamp)
        if typables and typables[0].value.strip():
            button = _submit_button(observation.elements)
            if button is not None:
                return Decision(operation="CLICK", confidence=0.9, click_target=button.index, **stamp)
            return Decision(operation="PRESS_ENTER", confidence=0.86, type_target=typables[0].index, **stamp)
        clicks = rank_by_goal([element for element in observation.elements if element.kind == "click"], goal)
        if clicks and any(token in clicks[0].name.lower() for token in goal_tokens(goal)):
            return Decision(operation="CLICK", confidence=0.88, click_target=clicks[0].index, **stamp)
        if sum(item.get("operation") == "SCROLL_DOWN" for item in history) >= 2:
            reason = "No control on this page matches the goal."
            return Decision(operation="BLOCKED", confidence=0.8, reason=reason, **stamp)
        return Decision(operation="SCROLL_DOWN", confidence=0.7, **stamp)


__all__ = ["FixturePolicy"]
