"""Jev request shape and answer parsing. No live provider."""

from __future__ import annotations

import json

import httpx
import pytest

from core_ai.types import Message

from browser_agent.models import Element, Observation
from browser_agent.policy import (
    DirectJevClient,
    FixturePolicy,
    JevPolicy,
    VercelJevClient,
    decision_from_answers,
)
from browser_agent.questions import build_questions, build_state, text_candidates


def _page(*, query: str = "", submitted: bool = False) -> Observation:
    text = "Symphony Books. Search the catalog."
    if submitted:
        text += " The Alps Guide — $18 — A travel guide to alpine huts."
    return Observation(
        url="https://books.example/catalog",
        title="Symphony Books",
        text=text,
        elements=[
            Element(index=1, role="textbox", name="Search books", value=query, kind="type"),
            Element(index=2, role="button", name="Search", kind="click"),
        ],
    )


def test_text_candidates_take_the_search_phrase() -> None:
    assert text_candidates('Search for travel and report the price of The Alps Guide.') == ["travel"]
    assert text_candidates('Type "ZRH" then continue.')[0] == "ZRH"


def test_questions_offer_type_only_when_a_field_exists() -> None:
    page = _page()
    questions = build_questions(page, "Search for travel and stop.", ["travel"])
    assert "TYPE_TEXT" in questions["operation"]["criteria"]
    assert questions["type_value"]["criteria"]["travel"].startswith("Type this exact string")
    buttons_only = Observation(
        url="https://example.test",
        title="Home",
        text="Home",
        elements=[Element(index=1, role="link", name="Espresso", kind="click")],
    )
    bare = build_questions(buttons_only, "Open Espresso", [])
    assert "TYPE_TEXT" not in bare["operation"]["criteria"]
    assert "type_target" not in bare
    assert "1" in bare["click_target"]["criteria"]


def test_decision_parser_reads_choice_and_boolean() -> None:
    decision = decision_from_answers(
        {
            "operation": {
                "type": "choice",
                "choice": "CLICK",
                "probabilities": {"CLICK": 0.91, "DONE": 0.02},
            },
            "click_target": {"type": "choice", "choice": "2", "probabilities": {"2": 0.8}},
            "goal_met": {"type": "boolean", "probability": 0.1},
        },
        model="typesafe-ai/jev",
        provider="vercel",
        offered_operations={"CLICK", "DONE", "BLOCKED"},
    )
    assert decision.operation == "CLICK"
    assert decision.click_target == 2
    assert decision.confidence == pytest.approx(0.91)
    assert decision.goal_met is False


def test_uncalibrated_choice_is_not_a_zero() -> None:
    decision = decision_from_answers(
        {"operation": {"type": "choice", "choice": "SCROLL_DOWN"}},
        model="typesafe-ai/jev",
        provider="vercel",
        offered_operations={"SCROLL_DOWN", "DONE"},
    )
    assert decision.confidence == 1.0


def test_select_target_splits_index_and_option() -> None:
    decision = decision_from_answers(
        {
            "operation": {"type": "choice", "choice": "SELECT", "confidence": 0.77},
            "select_target": {"type": "choice", "choice": "4:Economy"},
            "goal_met": {"type": "noul", "noul": 0.2},
        },
        model="jev-latest",
        provider="typesafe",
        offered_operations={"SELECT", "DONE"},
    )
    assert decision.select_index == 4
    assert decision.select_option == "Economy"
    assert decision.goal_met is False


def test_unknown_operation_blocks() -> None:
    decision = decision_from_answers(
        {"operation": {"type": "choice", "choice": "NAVIGATE"}},
        model="typesafe-ai/jev",
        provider="vercel",
        offered_operations={"CLICK", "DONE"},
    )
    assert decision.operation == "BLOCKED"


@pytest.mark.asyncio
async def test_vercel_client_posts_evaluation_model() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["model"] = request.headers.get("ai-model-id")
        captured["spec"] = request.headers.get("ai-evaluation-model-specification-version")
        return httpx.Response(
            200,
            json={
                "model": "typesafe-ai/jev",
                "answers": {
                    "operation": {"type": "choice", "choice": "CLICK", "probabilities": {"CLICK": 0.88}},
                    "click_target": {"type": "choice", "choice": "2"},
                    "goal_met": {"type": "boolean", "probability": 0.05},
                },
            },
        )

    page = _page()
    goal = "Search for travel and report the price."
    questions = build_questions(page, goal, ["travel"])
    state = build_state(goal, page, [])
    client = VercelJevClient(api_key="gw-test", transport=httpx.MockTransport(handler))
    policy = JevPolicy(client, model="typesafe-ai/jev", provider="vercel")
    decision = await policy.choose(goal=goal, observation=page, history=[], candidates=["travel"])
    payload = captured["payload"]
    assert captured["path"] == "/v4/ai/evaluation-model"
    assert captured["model"] == "typesafe-ai/jev"
    assert captured["spec"] == "4"
    assert isinstance(payload, dict)
    assert payload["state"]["goal"] == goal
    assert payload["questions"]["operation"]["type"] == "choice"
    assert "CLICK" in payload["questions"]["operation"]["criteria"]
    # The explicit state/questions message is what the shared helper expects.
    assert evaluation_round_trip(payload) == payload
    assert decision.operation == "CLICK"
    assert decision.click_target == 2
    assert questions["operation"]["type"] == "choice"
    assert state["url"].endswith("/catalog")


def evaluation_round_trip(payload: dict) -> dict:
    from core_ai.providers.vercel_evaluation import evaluation_request_body

    return evaluation_request_body([Message(role="user", content=json.dumps(payload))])


@pytest.mark.asyncio
async def test_typesafe_client_uses_noul() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "operation": {"type": "choice", "choice": "DONE", "confidence": 0.94},
                    "goal_met": {"type": "noul", "noul": 0.94},
                }
            },
        )

    client = DirectJevClient(
        api_key="ts-test",
        url="https://api.typesafe.ai/v1/systemone",
        model="jev-latest",
        provider="typesafe",
        transport=httpx.MockTransport(handler),
    )
    policy = JevPolicy(client, model="jev-latest", provider="typesafe")
    decision = await policy.choose(
        goal="done already",
        observation=_page(submitted=True),
        history=[],
        candidates=[],
    )
    payload = captured["payload"]
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert isinstance(payload, dict)
    assert payload["model"] == "jev-latest"
    assert payload["questions"]["goal_met"]["type"] == "noul"
    assert decision.operation == "DONE"
    assert decision.goal_met is True


@pytest.mark.asyncio
async def test_fixture_types_then_clicks_then_stops() -> None:
    policy = FixturePolicy()
    goal = "Search for travel and report the price of The Alps Guide."
    first = await policy.choose(goal=goal, observation=_page(), history=[], candidates=["travel"])
    assert first.operation == "TYPE_TEXT"
    assert first.type_value == "travel"
    second = await policy.choose(
        goal=goal,
        observation=_page(query="travel"),
        history=[{"operation": "TYPE_TEXT"}],
        candidates=["travel"],
    )
    assert second.operation == "CLICK"
    assert second.click_target == 2
    third = await policy.choose(
        goal=goal,
        observation=_page(query="travel", submitted=True),
        history=[],
        candidates=["travel"],
    )
    assert third.operation == "DONE"
