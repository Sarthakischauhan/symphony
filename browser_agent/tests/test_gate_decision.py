"""The gate decides what may run: repeats, targets, URLs, goal_met, and the floor."""

from __future__ import annotations

from browser_agent.gate_decision import gate, repeat_key
from browser_agent.models import Decision, Element, Observation

PAGE = Observation(
    url="https://books.example/catalog",
    text="Symphony Books",
    elements=[
        Element(index=1, role="textbox", name="Search books", kind="type"),
        Element(index=2, role="button", name="Search"),
    ],
)


def _gate(decision: Decision, observation: Observation = PAGE, history: list | None = None) -> Decision:
    return gate(decision, observation, history or [], min_confidence=0.25, goal_met_stop=0.92)


def test_third_identical_action_with_writer_text_is_blocked() -> None:
    typed = Decision(operation="TYPE_TEXT", confidence=0.9, type_target=1, type_value="travel")
    history = [{"repeat_key": repeat_key(typed, PAGE)}] * 2
    assert _gate(typed, history=history[:1]).operation == "TYPE_TEXT"
    blocked = _gate(typed, history=history)
    assert blocked.operation == "BLOCKED"
    assert "three times" in blocked.reason
    other_text = typed.model_copy(update={"type_value": "alps"})
    assert _gate(other_text, history=history).operation == "TYPE_TEXT"
    changed_page = PAGE.model_copy(update={"text": "Symphony Books. The Alps Guide"})
    assert _gate(typed, changed_page, history).operation == "TYPE_TEXT"


def test_action_without_a_live_target_is_blocked() -> None:
    assert _gate(Decision(operation="CLICK", confidence=0.9)).operation == "BLOCKED"
    assert _gate(Decision(operation="CLICK", confidence=0.9, click_target=9)).operation == "BLOCKED"
    assert _gate(Decision(operation="SELECT", confidence=0.9, select_index=2)).operation == "SELECT"
    no_text = _gate(Decision(operation="TYPE_TEXT", confidence=0.9, type_target=1))
    assert (no_text.operation, no_text.reason) == ("BLOCKED", "TYPE_TEXT was chosen but no string was available.")


def test_low_confidence_action_is_blocked_but_scroll_is_not() -> None:
    assert _gate(Decision(operation="CLICK", confidence=0.1, click_target=2)).operation == "BLOCKED"
    assert _gate(Decision(operation="SCROLL_DOWN", confidence=0.1)).operation == "SCROLL_DOWN"


def test_confident_goal_met_turns_a_passive_step_into_done() -> None:
    waiting = Decision(operation="WAIT", confidence=0.5, goal_met=True, goal_met_confidence=0.95)
    assert _gate(waiting).operation == "DONE"
    unsure = waiting.model_copy(update={"goal_met_confidence": 0.6})
    assert _gate(unsure).operation == "WAIT"


def test_non_http_page_blocks_actions() -> None:
    data_page = PAGE.model_copy(update={"url": "data:text/html,<p>hi</p>"})
    assert _gate(Decision(operation="CLICK", confidence=0.9, click_target=2), data_page).operation == "BLOCKED"
    assert _gate(Decision(operation="DONE", confidence=0.9), data_page).operation == "DONE"
