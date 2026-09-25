"""Build the single Jev request for one browser step.

One call asks for the operation and, speculatively, the target for every
operation that the current page can actually perform. Code executes only
the target that matches the chosen operation.
"""

from __future__ import annotations

import re
from typing import Any

from browser_agent.models import Element, Observation

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "onto",
    "your", "page", "then", "when", "stop", "once", "visible", "report",
}

_CANDIDATE = re.compile(
    r"(?:search(?:\s+for)?|type|enter|query|look up|fill in)\s+(.+?)(?:\s+and\s+|\s+then\s+|[,.]|$)",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"([^"]{1,80})"|\'([^\']{1,80})\'')


def text_candidates(goal: str) -> list[str]:
    """Strings the caller already supplied. Jev may choose one; it cannot invent one."""
    found: list[str] = []
    for match in _QUOTED.finditer(goal):
        text = (match.group(1) or match.group(2) or "").strip()
        if text and text not in found:
            found.append(text)
    lead = _CANDIDATE.search(goal)
    if lead:
        text = lead.group(1).strip(" \"'")
        if text and text not in found:
            found.insert(0, text)
    return found[:8]


def _rank(elements: list[Element], goal: str) -> list[Element]:
    tokens = set(re.findall(r"[a-z0-9]{3,}", goal.lower())) - _STOP

    def score(element: Element) -> int:
        name = element.name.lower()
        return sum(1 for token in tokens if token in name)

    return sorted(elements, key=score, reverse=True)


def _criteria(elements: list[Element], limit: int = 40) -> dict[str, str]:
    criteria: dict[str, str] = {}
    for element in elements[:limit]:
        criteria[str(element.index)] = element.label()
    return criteria


def build_questions(observation: Observation, goal: str, candidates: list[str]) -> dict[str, Any]:
    ranked = _rank(observation.elements, goal)
    clickables = [element for element in ranked if element.kind in {"click", "type", "select"}]
    typables = [element for element in ranked if element.kind == "type"]
    selects = [element for element in ranked if element.kind == "select"]

    operations: dict[str, str] = {}
    if clickables:
        operations["CLICK"] = "Activate a button, link, or other control."
    if typables:
        operations["TYPE_TEXT"] = "Type into a text field that is empty or holds the wrong value."
        operations["PRESS_ENTER"] = "Submit the current text field with Enter."
    if selects:
        operations["SELECT"] = "Choose an option in a dropdown."
    operations["SCROLL_DOWN"] = "Scroll down to reveal more of the page."
    operations["SCROLL_UP"] = "Scroll up toward the top of the page."
    operations["WAIT"] = "Wait for the page to finish updating."
    operations["DONE"] = "The goal is already satisfied on this page. Stop."
    operations["BLOCKED"] = "A login wall, captcha, or missing control makes progress impossible."

    questions: dict[str, Any] = {
        "operation": {
            "type": "choice",
            "instructions": (
                "Pick the single next browser operation that moves toward the goal in state.goal. "
                "Choose DONE only when the requested fact or page is already visible. "
                "Choose TYPE_TEXT before CLICK when a required field is empty. "
                "Do not repeat an action already listed in state.history."
            ),
            "criteria": operations,
        },
        "goal_met": {
            "type": "boolean",
            "instructions": (
                "Is the user's goal already satisfied by the current page, "
                "with the requested information visible in state.page_text?"
            ),
        },
    }
    if clickables:
        questions["click_target"] = {
            "type": "choice",
            "instructions": "If the operation is CLICK, which element index should be clicked?",
            "criteria": _criteria(clickables),
        }
    if typables:
        questions["type_target"] = {
            "type": "choice",
            "instructions": "If the operation is TYPE_TEXT or PRESS_ENTER, which field index?",
            "criteria": _criteria(typables),
        }
    if selects:
        select_criteria: dict[str, str] = {}
        for element in selects[:20]:
            options = element.options or ["(current)"]
            for option in options[:12]:
                select_criteria[f"{element.index}:{option}"] = f"{element.label()} → {option}"
        if select_criteria:
            questions["select_target"] = {
                "type": "choice",
                "instructions": "If the operation is SELECT, which element and option?",
                "criteria": select_criteria,
            }
    if typables and candidates:
        questions["type_value"] = {
            "type": "choice",
            "instructions": (
                "If the operation is TYPE_TEXT, which supplied string should be typed? "
                "Pick none only if none of the strings belong in the field."
            ),
            "criteria": {
                **{candidate: f"Type this exact string: {candidate}" for candidate in candidates},
                "none": "None of these strings should be typed.",
            },
        }
    return questions


def build_state(goal: str, observation: Observation, history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "goal": goal,
        "url": observation.url,
        "title": observation.title,
        "page_text": observation.text[:4000],
        "elements": [element.compact() for element in observation.elements[:60]],
        "history": history[-8:],
    }


def for_noul_api(questions: dict[str, Any]) -> dict[str, Any]:
    """TypeSafe and OpenRouter call a yes/no question `noul`, not `boolean`."""
    converted: dict[str, Any] = {}
    for name, question in questions.items():
        if isinstance(question, dict) and question.get("type") == "boolean":
            rewritten = dict(question)
            rewritten["type"] = "noul"
            converted[name] = rewritten
        else:
            converted[name] = question
    return converted


__all__ = [
    "build_questions",
    "build_state",
    "for_noul_api",
    "text_candidates",
]
