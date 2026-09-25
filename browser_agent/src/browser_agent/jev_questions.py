"""Build the single Jev request for one browser step.

One call asks for the operation and, speculatively, the target for every
operation that the current page can actually perform. Code executes only
the target that matches the chosen operation.
"""

from __future__ import annotations

from typing import Any

from browser_agent.models import Element, Observation
from browser_agent.rank_elements import rank_by_goal
from browser_agent.session import MAX_ELEMENTS, MAX_OPTIONS, MAX_PAGE_TEXT

_OPERATION_INSTRUCTIONS = (
    "Pick the single next browser operation that moves toward the goal in state.goal. "
    "Choose DONE only when the requested fact or page is already visible. "
    "Choose TYPE_TEXT before CLICK when a required field is empty. "
    "Do not repeat an action already listed in state.history."
)


def _criteria(elements: list[Element], limit: int = 40) -> dict[str, str]:
    return {str(element.index): element.label() for element in elements[:limit]}


def _choice(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def _operations(elements: list[Element], typables: list[Element], selects: list[Element]) -> dict[str, str]:
    """Only the operations this page can perform, plus the always-available ones."""
    operations: dict[str, str] = {}
    if elements:
        operations["CLICK"] = "Activate a button, link, or other control."
    if typables:
        operations["TYPE_TEXT"] = "Type into a text field that is empty or holds the wrong value."
        operations["PRESS_ENTER"] = "Submit the current text field with Enter."
    if selects:
        operations["SELECT"] = "Choose an option in a dropdown."
    return operations | {
        "SCROLL_DOWN": "Scroll down to reveal more of the page.",
        "SCROLL_UP": "Scroll up toward the top of the page.",
        "WAIT": "Wait for the page to finish updating.",
        "DONE": "The goal is already satisfied on this page. Stop.",
        "BLOCKED": "A login wall, captcha, or missing control makes progress impossible.",
    }


def build_questions(observation: Observation, goal: str, candidates: list[str]) -> dict[str, Any]:
    """The ``questions`` object: operation, goal_met, and one target question per available operation."""
    ranked = rank_by_goal(observation.elements, goal)
    typables = [element for element in ranked if element.kind == "type"]
    selects = [element for element in ranked if element.kind == "select"]
    questions: dict[str, Any] = {
        "operation": _choice(_OPERATION_INSTRUCTIONS, _operations(ranked, typables, selects)),
        "goal_met": {
            "type": "boolean",
            "instructions": (
                "Is the user's goal already satisfied by the current page, "
                "with the requested information visible in state.page_text?"
            ),
        },
    }
    if ranked:
        questions["click_target"] = _choice(
            "If the operation is CLICK, which element index should be clicked?", _criteria(ranked)
        )
    if typables:
        questions["type_target"] = _choice(
            "If the operation is TYPE_TEXT or PRESS_ENTER, which field index?", _criteria(typables)
        )
    select_criteria = {
        f"{element.index}:{option}": f"{element.label()} → {option}"
        for element in selects[:20]
        for option in element.options[:MAX_OPTIONS]
    }
    if select_criteria:
        questions["select_target"] = _choice("If the operation is SELECT, which element and option?", select_criteria)
    if typables and candidates:
        questions["type_value"] = _choice(
            "If the operation is TYPE_TEXT, which supplied string should be typed? "
            "Pick none only if none of the strings belong in the field.",
            {candidate: f"Type this exact string: {candidate}" for candidate in candidates}
            | {"none": "None of these strings should be typed."},
        )
    return questions


def build_state(goal: str, observation: Observation, history: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``state`` object: goal, page, secret-safe element table, and recent history."""
    return {
        "goal": goal,
        "url": observation.url,
        "title": observation.title,
        "page_text": observation.text[:MAX_PAGE_TEXT],
        "elements": [element.compact() for element in observation.elements[:MAX_ELEMENTS]],
        "history": history[-8:],
    }


def for_noul_api(questions: dict[str, Any]) -> dict[str, Any]:
    """TypeSafe and OpenRouter call a yes/no question ``noul``, not ``boolean``."""
    return {
        name: question | {"type": "noul"} if question.get("type") == "boolean" else question
        for name, question in questions.items()
    }


__all__ = ["build_questions", "build_state", "for_noul_api"]
