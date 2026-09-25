"""The loop executes Jev answers and stamps control-plane events."""

from __future__ import annotations

import asyncio
import json
import re

from fakes import AnswerJev, MemorySession, ScriptedJev, StaticTextWriter

from browser_agent.agent import BrowserAgent
from browser_agent.fixture_policy import FixturePolicy
from browser_agent.jev_policy import JevPolicy
from browser_agent.models import Element, Observation

GOAL = "Search for travel and report the price of The Alps Guide."
TYPE_ONE = {
    "operation": {"type": "choice", "choice": "TYPE_TEXT", "confidence": 0.9},
    "type_target": {"type": "choice", "choice": "1"},
    "goal_met": {"type": "boolean", "probability": 0.0},
}


def _jev(client) -> JevPolicy:
    return JevPolicy(client, model="typesafe-ai/jev", provider="vercel")


def _kinds(agent: BrowserAgent) -> list[str]:
    return [event.event_type for event in agent.sink.events]


def test_jev_policy_drives_the_catalog() -> None:
    client = ScriptedJev()
    agent = BrowserAgent(_jev(client), max_steps=6)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "done"
    assert (result.provider, result.model) == ("vercel", "typesafe-ai/jev")
    assert "$18" in result.output_text
    assert [step.operation for step in result.steps] == ["TYPE_TEXT", "CLICK", "DONE"]
    assert result.steps[0].type_value == "travel"
    kinds = _kinds(agent)
    assert (kinds[0], kinds[-1]) == ("run_started", "run_completed")
    decisions = [event.payload for event in agent.sink.events if event.event_type == "jev_decision"]
    assert [item["operation"] for item in decisions] == ["TYPE_TEXT", "CLICK", "DONE"]
    assert decisions[0]["run_id"] and decisions[0]["agent_id"] == "browser"
    assert decisions[0]["source"] == "browser"
    assert client.states[0]["goal"].startswith("Search for travel")


def test_fixture_policy_reaches_the_same_page() -> None:
    result = asyncio.run(BrowserAgent(FixturePolicy(), max_steps=6).run(GOAL, MemorySession()))
    assert (result.status, result.provider) == ("done", "fixture")
    assert "$18" in result.output_text


def test_text_writer_is_used_only_when_jev_does_not_supply_a_string() -> None:
    writer = StaticTextWriter("travel")
    session = MemorySession()
    agent = BrowserAgent(_jev(AnswerJev(TYPE_ONE)), max_steps=1, text_writer=writer)
    result = asyncio.run(agent.run("Find a book.", session))
    assert session.query == "travel"
    assert (result.steps[0].operation, result.steps[0].type_value) == ("TYPE_TEXT", "travel")
    literal = AnswerJev(TYPE_ONE | {"type_value": {"type": "choice", "choice": "alps"}})
    asyncio.run(BrowserAgent(_jev(literal), max_steps=1, text_writer=writer).run("Find alps.", MemorySession()))
    assert writer.calls == 1


class PasswordPage:
    """A login field the page marked secret, with a generic placeholder."""

    def __init__(self) -> None:
        self.typed = ""

    async def observe(self) -> Observation:
        field = Element(index=1, role="input", name="Enter code", value=self.typed, kind="type", secret=True)
        return Observation(url="https://example.test/login", title="Login", text="Login", elements=[field])

    async def act(self, decision) -> None:
        self.typed = decision.type_value


def test_secret_values_stay_off_events_and_steps() -> None:
    client = AnswerJev(TYPE_ONE | {"type_value": {"type": "choice", "choice": "s3cret"}})
    page = PasswordPage()
    agent = BrowserAgent(_jev(client), max_steps=3)
    result = asyncio.run(agent.run('Type "s3cret" into the field.', page))
    assert page.typed == "s3cret"
    decision = next(event for event in agent.sink.events if event.event_type == "jev_decision")
    assert decision.payload["type_value"] == "***"
    assert result.steps[0].type_value == "***"
    assert "s3cret" not in result.steps[0].note
    history = [item for state in client.states for item in state["history"]]
    assert len(history) == 3
    assert all(set(item) == {"step", "operation", "target", "url", "value"} for item in history)
    assert not re.search(r"\b[0-9a-f]{16}\b", json.dumps(history))
    assert all(element["value"] in {"", "***"} for state in client.states for element in state["elements"])


def test_step_limit_is_limited_with_run_limit_exceeded() -> None:
    scroll = {"operation": {"type": "choice", "choice": "SCROLL_DOWN", "confidence": 0.9}}
    agent = BrowserAgent(_jev(AnswerJev(scroll)), max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "limited"
    assert _kinds(agent)[-1] == "run_limit_exceeded"


def test_exception_is_error_with_run_failed() -> None:
    class Broken:
        async def complete(self, state: dict, questions: dict) -> dict:
            raise RuntimeError("gateway down")

    agent = BrowserAgent(_jev(Broken()), max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert (result.status, result.message) == ("error", "gateway down")
    failed = agent.sink.events[-1]
    assert failed.event_type == "run_failed"
    assert failed.payload["error_type"] == "RuntimeError"


def test_repeated_writer_text_is_blocked_not_limited() -> None:
    agent = BrowserAgent(_jev(AnswerJev(TYPE_ONE)), max_steps=6, text_writer=StaticTextWriter("travel"))

    class StuckPage(MemorySession):
        async def act(self, decision) -> None:
            del decision

    result = asyncio.run(agent.run("Find a book.", StuckPage()))
    assert result.status == "blocked"
    assert [step.operation for step in result.steps] == ["TYPE_TEXT", "TYPE_TEXT", "BLOCKED"]
    assert "three times" in result.message


def test_missing_target_is_blocked_not_success() -> None:
    click = {"operation": {"type": "choice", "choice": "CLICK", "confidence": 0.9}}
    agent = BrowserAgent(_jev(AnswerJev(click)), max_steps=3)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "blocked"
    assert "tool_execution_started" not in _kinds(agent)


def test_reused_agent_gets_a_new_run_id() -> None:
    agent = BrowserAgent(FixturePolicy(), max_steps=6)
    asyncio.run(agent.run(GOAL, MemorySession()))
    asyncio.run(agent.run(GOAL, MemorySession()))
    starts = [event.payload for event in agent.sink.events if event.event_type == "run_started"]
    assert starts[0]["run_id"] != starts[1]["run_id"]
