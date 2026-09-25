"""The loop executes Jev answers and stamps control-plane events."""

from __future__ import annotations

import pytest

from browser_agent.agent import BrowserAgent
from browser_agent.policy import FixturePolicy, JevPolicy
from browser_agent.session import MemorySession
from browser_agent.text import StaticTextWriter


class ScriptedJev:
    """Speaks the evaluation-model answer schema for the catalog task."""

    def __init__(self) -> None:
        self.states: list[dict] = []

    async def complete(self, state: dict, questions: dict) -> dict:
        del questions
        self.states.append(state)
        text = state["page_text"]
        if "$18" in text:
            return {
                "model": "typesafe-ai/jev",
                "answers": {
                    "operation": {"type": "choice", "choice": "DONE", "probabilities": {"DONE": 0.96}},
                    "goal_met": {"type": "boolean", "probability": 0.97},
                },
            }
        field = next(element for element in state["elements"] if element["kind"] == "type")
        if not field["value"]:
            return {
                "model": "typesafe-ai/jev",
                "answers": {
                    "operation": {
                        "type": "choice",
                        "choice": "TYPE_TEXT",
                        "probabilities": {"TYPE_TEXT": 0.93},
                    },
                    "type_target": {"type": "choice", "choice": str(field["index"])},
                    "type_value": {"type": "choice", "choice": "travel", "probabilities": {"travel": 0.95}},
                    "goal_met": {"type": "boolean", "probability": 0.04},
                },
            }
        button = next(element for element in state["elements"] if element["kind"] == "click")
        return {
            "model": "typesafe-ai/jev",
            "answers": {
                "operation": {"type": "choice", "choice": "CLICK", "probabilities": {"CLICK": 0.91}},
                "click_target": {"type": "choice", "choice": str(button["index"])},
                "goal_met": {"type": "boolean", "probability": 0.08},
            },
        }


@pytest.mark.asyncio
async def test_jev_policy_drives_the_catalog() -> None:
    client = ScriptedJev()
    agent = BrowserAgent(
        JevPolicy(client, model="typesafe-ai/jev", provider="vercel"),
        max_steps=6,
    )
    result = await agent.run(
        "Search for travel and report the price of The Alps Guide.",
        MemorySession(),
    )
    assert result.status == "done"
    assert result.provider == "vercel"
    assert result.model == "typesafe-ai/jev"
    assert "$18" in result.output_text
    assert [step.operation for step in result.steps] == ["TYPE_TEXT", "CLICK", "DONE"]
    assert result.steps[0].type_value == "travel"
    kinds = [event.event_type for event in agent.sink.events]
    assert kinds[0] == "run_started"
    assert "jev_decision" in kinds
    assert kinds[-1] == "run_completed"
    decisions = [event.payload for event in agent.sink.events if event.event_type == "jev_decision"]
    assert [item["operation"] for item in decisions] == ["TYPE_TEXT", "CLICK", "DONE"]
    assert decisions[0]["run_id"]
    assert decisions[0]["agent_id"] == "browser"
    assert "elements" in client.states[0]
    assert client.states[0]["goal"].startswith("Search for travel")


@pytest.mark.asyncio
async def test_fixture_policy_reaches_the_same_page() -> None:
    agent = BrowserAgent(FixturePolicy(), max_steps=6)
    result = await agent.run(
        "Search for travel and report the price of The Alps Guide.",
        MemorySession(),
    )
    assert result.status == "done"
    assert result.provider == "fixture"
    assert "$18" in result.output_text


@pytest.mark.asyncio
async def test_text_writer_is_used_only_when_jev_does_not_supply_a_string() -> None:
    class TypeWithoutValue:
        async def complete(self, state: dict, questions: dict) -> dict:
            del questions
            if state["elements"][0]["value"]:
                return {
                    "answers": {
                        "operation": {"type": "choice", "choice": "DONE", "confidence": 0.99},
                        "goal_met": {"type": "boolean", "probability": 0.2},
                    }
                }
            return {
                "answers": {
                    "operation": {"type": "choice", "choice": "TYPE_TEXT", "confidence": 0.9},
                    "type_target": {"type": "choice", "choice": "1"},
                    "goal_met": {"type": "boolean", "probability": 0.0},
                }
            }

    writer = StaticTextWriter("travel")
    agent = BrowserAgent(
        JevPolicy(TypeWithoutValue(), model="typesafe-ai/jev", provider="vercel"),
        max_steps=4,
        text_writer=writer,
    )
    session = MemorySession()
    result = await agent.run("Find a book.", session)
    assert session.query == "travel"
    assert result.steps[0].operation == "TYPE_TEXT"
    assert result.steps[0].type_value == "travel"


@pytest.mark.asyncio
async def test_password_values_are_redacted_on_the_event() -> None:
    class TypePassword:
        async def complete(self, state: dict, questions: dict) -> dict:
            del state, questions
            return {
                "answers": {
                    "operation": {"type": "choice", "choice": "TYPE_TEXT", "confidence": 0.99},
                    "type_target": {"type": "choice", "choice": "1"},
                    "type_value": {"type": "choice", "choice": "s3cret", "probabilities": {"s3cret": 0.99}},
                    "goal_met": {"type": "boolean", "probability": 0.0},
                }
            }

    from browser_agent.models import Element, Observation

    class PasswordPage:
        def __init__(self) -> None:
            self.typed = ""

        async def observe(self) -> Observation:
            return Observation(
                url="https://example.test/login",
                title="Login",
                text="Login",
                elements=[
                    Element(index=1, role="textbox", name="Password", value=self.typed, kind="type")
                ],
            )

        async def act(self, decision, text: str) -> None:
            del decision
            self.typed = text

        async def close(self) -> None:
            return None

    page = PasswordPage()
    agent = BrowserAgent(
        JevPolicy(TypePassword(), model="typesafe-ai/jev", provider="vercel"),
        max_steps=1,
    )
    await agent.run('Type "s3cret" into the password field.', page)
    assert page.typed == "s3cret"
    decision = next(event for event in agent.sink.events if event.event_type == "jev_decision")
    assert decision.payload["type_value"] == "***"
