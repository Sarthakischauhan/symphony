"""Jev request shape and answer parsing. No live provider."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from browser_agent.fixture_policy import FixturePolicy
from browser_agent.goal_text_candidates import text_candidates
from browser_agent.jev_answers import DecisionError, decision_from_answers
from browser_agent.jev_client import JevClient
from browser_agent.jev_credentials import TYPESAFE_URL, JevEndpoint
from browser_agent.jev_policy import JevPolicy
from browser_agent.jev_questions import build_questions
from browser_agent.models import Element, Observation
from browser_agent.rank_elements import rank_by_goal

GOAL = "Search for travel and report the price of The Alps Guide."


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


def _decide(answers: object, offered: set[str]):
    return decision_from_answers(answers, model="typesafe-ai/jev", provider="vercel", offered_operations=offered)


def test_text_candidates_take_the_search_phrase() -> None:
    assert text_candidates(GOAL) == ["travel"]
    assert text_candidates('Type "ZRH" then continue.')[0] == "ZRH"


def test_rank_puts_goal_words_first() -> None:
    links = [Element(index=1, role="link", name="Home"), Element(index=2, role="link", name="Espresso machines")]
    assert [element.index for element in rank_by_goal(links, "Open the espresso page")] == [2, 1]


def test_questions_offer_type_only_when_a_field_exists() -> None:
    questions = build_questions(_page(), "Search for travel and stop.", ["travel"])
    assert "TYPE_TEXT" in questions["operation"]["criteria"]
    assert questions["type_value"]["criteria"]["travel"].startswith("Type this exact string")
    links = Observation(url="https://example.test", elements=[Element(index=1, role="link", name="Espresso")])
    bare = build_questions(links, "Open Espresso", [])
    assert "TYPE_TEXT" not in bare["operation"]["criteria"]
    assert "type_target" not in bare
    assert "1" in bare["click_target"]["criteria"]


def test_select_without_options_offers_no_select_target() -> None:
    dropdown = Element(index=1, role="select", name="Class", kind="select")
    empty = Observation(url="https://example.test", elements=[dropdown])
    assert "select_target" not in build_questions(empty, "Pick a class", [])


def test_decision_parser_reads_choice_and_boolean() -> None:
    decision = _decide(
        {
            "operation": {"type": "choice", "choice": "CLICK", "probabilities": {"CLICK": 0.91, "DONE": 0.02}},
            "click_target": {"type": "choice", "choice": "2", "probabilities": {"2": 0.8}},
            "goal_met": {"type": "boolean", "probability": 0.1},
        },
        {"CLICK", "DONE", "BLOCKED"},
    )
    assert (decision.operation, decision.click_target, decision.goal_met) == ("CLICK", 2, False)
    assert decision.confidence == pytest.approx(0.91)


def test_uncalibrated_choice_is_not_a_zero() -> None:
    assert _decide({"operation": {"type": "choice", "choice": "SCROLL_DOWN"}}, {"SCROLL_DOWN"}).confidence == 1.0


def test_select_target_splits_index_and_option() -> None:
    decision = _decide(
        {
            "operation": {"type": "choice", "choice": "SELECT", "confidence": 0.77},
            "select_target": {"type": "choice", "choice": "4:Economy"},
            "goal_met": {"type": "noul", "noul": 0.2},
        },
        {"SELECT", "DONE"},
    )
    assert (decision.select_index, decision.select_option, decision.goal_met) == (4, "Economy", False)


def test_unknown_operation_blocks_with_a_reason() -> None:
    decision = _decide({"operation": {"type": "choice", "choice": "NAVIGATE"}}, {"CLICK", "DONE"})
    assert decision.operation == "BLOCKED"
    assert "not available" in decision.reason
    with pytest.raises(DecisionError):
        _decide({}, {"DONE"})


def _mock(captured: dict, answers: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(url=str(request.url), headers=request.headers, payload=json.loads(request.content))
        return httpx.Response(200, json={"model": "typesafe-ai/jev", "answers": answers})

    return httpx.MockTransport(handler)


def test_vercel_client_posts_evaluation_model() -> None:
    captured: dict = {}
    answers = {
        "operation": {"type": "choice", "choice": "CLICK", "probabilities": {"CLICK": 0.88}},
        "click_target": {"type": "choice", "choice": "2"},
        "goal_met": {"type": "boolean", "probability": 0.05},
    }
    url = "https://ai-gateway.vercel.sh/v4/ai/evaluation-model"
    client = JevClient.for_endpoint(JevEndpoint("vercel", "gw-test", "typesafe-ai/jev", url), _mock(captured, answers))
    policy = JevPolicy(client, model="typesafe-ai/jev", provider="vercel")
    decision = asyncio.run(policy.choose(goal=GOAL, observation=_page(), history=[], candidates=["travel"]))
    assert captured["url"] == url
    assert captured["headers"]["ai-model-id"] == "typesafe-ai/jev"
    assert captured["headers"]["ai-evaluation-model-specification-version"] == "4"
    assert captured["payload"]["state"]["goal"] == GOAL
    assert captured["payload"]["questions"]["goal_met"]["type"] == "boolean"
    assert "CLICK" in captured["payload"]["questions"]["operation"]["criteria"]
    assert (decision.operation, decision.click_target) == ("CLICK", 2)


def test_typesafe_client_uses_noul() -> None:
    captured: dict = {}
    answers = {
        "operation": {"type": "choice", "choice": "DONE", "confidence": 0.94},
        "goal_met": {"type": "noul", "noul": 0.94},
    }
    endpoint = JevEndpoint("typesafe", "ts-test", "jev-latest", TYPESAFE_URL)
    client = JevClient.for_endpoint(endpoint, _mock(captured, answers))
    policy = JevPolicy(client, model="jev-latest", provider="typesafe")
    decision = asyncio.run(policy.choose(goal="done", observation=_page(submitted=True), history=[], candidates=[]))
    assert captured["url"] == TYPESAFE_URL
    assert captured["headers"]["authorization"] == "Bearer ts-test"
    assert captured["payload"]["model"] == "jev-latest"
    assert captured["payload"]["questions"]["goal_met"]["type"] == "noul"
    assert (decision.operation, decision.goal_met) == ("DONE", True)


def test_non_object_reply_is_a_decision_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[1, 2]))
    client = JevClient.for_endpoint(JevEndpoint("typesafe", "k", "jev-latest", TYPESAFE_URL), transport)
    with pytest.raises(DecisionError):
        asyncio.run(client.complete({}, {}))


def test_fixture_types_then_clicks_then_stops() -> None:
    policy = FixturePolicy()

    def choose(page: Observation, history: list):
        return asyncio.run(policy.choose(goal=GOAL, observation=page, history=history, candidates=["travel"]))

    first = choose(_page(), [])
    assert (first.operation, first.type_value) == ("TYPE_TEXT", "travel")
    second = choose(_page(query="travel"), [{"operation": "TYPE_TEXT"}])
    assert (second.operation, second.click_target) == ("CLICK", 2)
    assert choose(_page(query="travel", submitted=True), []).operation == "DONE"
