"""Jev is the policy. A chat model is not asked which element to click.

The Vercel path reuses ``core_ai.providers.vercel_evaluation`` so the browser
agent speaks the same evaluation-model protocol as the rest of Symphony.
TypeSafe and OpenRouter are the same question payload on their decision APIs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional, Protocol

import httpx

from core_ai.providers.vercel_evaluation import (
    evaluation_model_url,
    evaluation_request_body,
    evaluation_request_headers,
)
from core_ai.types import Message

from browser_agent.models import Decision, Element, Observation
from browser_agent.questions import build_questions, build_state, for_noul_api, text_candidates

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
VERCEL_MODEL = "typesafe-ai/jev"

_PRICE = re.compile(r"\$\s?\d")
_GENERIC = {
    "search", "price", "report", "find", "click", "open", "page", "book",
    "books", "show", "tell", "give", "using", "where", "what", "when",
    "which", "from", "into", "with", "that", "this", "your", "stop",
}


class DecisionError(RuntimeError):
    pass


class Policy(Protocol):
    name: str
    provider: str

    async def choose(
        self,
        *,
        goal: str,
        observation: Observation,
        history: list[dict[str, Any]],
        candidates: list[str],
    ) -> Decision:
        ...


def _confidence(answer: dict[str, Any], choice: str) -> tuple[float, dict[str, float]]:
    probabilities: dict[str, float] = {}
    raw = answer.get("probabilities")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, (int, float)):
                probabilities[str(key)] = float(value)
    if choice and choice in probabilities:
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
    kind = str(answer.get("type") or "")
    if kind == "noul":
        value = answer.get("noul")
        if isinstance(value, (int, float)):
            probability = float(value)
            return probability >= 0.5, probability
    probability = answer.get("probability")
    if isinstance(probability, (int, float)):
        value = float(probability)
        return value >= 0.5, value
    if "value" in answer:
        chosen = bool(answer.get("value"))
        return chosen, 1.0 if chosen else 0.0
    return False, 0.0


def _choice(answers: dict[str, Any], name: str) -> tuple[str, float, dict[str, float]]:
    answer = answers.get(name)
    if not isinstance(answer, dict):
        return "", 0.0, {}
    choice = str(answer.get("choice") or "").strip()
    confidence, probabilities = _confidence(answer, choice)
    return choice, confidence, probabilities


def _index(raw: str) -> Optional[int]:
    head = raw.split(":", 1)[0].strip()
    if head.isdigit():
        return int(head)
    return None


def decision_from_answers(
    answers: object,
    *,
    model: str,
    provider: str,
    offered_operations: set[str],
) -> Decision:
    if not isinstance(answers, dict) or not answers:
        raise DecisionError("evaluation model returned no answers")
    operation, confidence, probabilities = _choice(answers, "operation")
    if operation not in offered_operations:
        operation = "BLOCKED"
        confidence = 0.0
    click_raw, _, _ = _choice(answers, "click_target")
    type_raw, _, _ = _choice(answers, "type_target")
    select_raw, _, _ = _choice(answers, "select_target")
    type_value, _, _ = _choice(answers, "type_value")
    if type_value == "none":
        type_value = ""
    goal_met, goal_confidence = _bool_confidence(answers.get("goal_met"))
    select_index = _index(select_raw) if select_raw else None
    select_option = ""
    if select_raw and ":" in select_raw:
        select_option = select_raw.split(":", 1)[1]
    return Decision(
        operation=operation,
        confidence=confidence,
        click_target=_index(click_raw) if click_raw else None,
        type_target=_index(type_raw) if type_raw else None,
        type_value=type_value,
        select_index=select_index,
        select_option=select_option,
        goal_met=goal_met,
        goal_met_confidence=goal_confidence,
        model=model,
        provider=provider,
        probabilities=probabilities,
    )


class VercelJevClient:
    """POST Symphony's evaluation-model endpoint. Model id defaults to typesafe-ai/jev."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = VERCEL_MODEL,
        base_url: str = "",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.transport = transport

    async def complete(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        payload = {"state": state, "questions": questions}
        body = evaluation_request_body([Message(role="user", content=json.dumps(payload))])
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.post(
                evaluation_model_url(self.base_url),
                json=body,
                headers=evaluation_request_headers(self.model, api_key=self.api_key),
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise DecisionError("evaluation model returned a non-object response")
        return data


class DirectJevClient:
    """TypeSafe ``/v1/systemone`` or OpenRouter ``/api/alpha/decisions``."""

    def __init__(
        self,
        *,
        api_key: str,
        url: str,
        model: str,
        provider: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.provider = provider
        self.transport = transport

    async def complete(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "state": state,
            "questions": for_noul_api(questions),
        }
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.post(
                self.url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise DecisionError("Jev returned a non-object response")
        return data


class JevPolicy:
    """Primary policy: one evaluation call picks the operation and the target."""

    def __init__(self, client: Any, *, model: str, provider: str) -> None:
        self.client = client
        self.model = model
        self.provider = provider
        self.name = model

    async def choose(
        self,
        *,
        goal: str,
        observation: Observation,
        history: list[dict[str, Any]],
        candidates: list[str],
    ) -> Decision:
        questions = build_questions(observation, goal, candidates)
        state = build_state(goal, observation, history)
        data = await self.client.complete(state, questions)
        answers = data.get("answers") if isinstance(data, dict) else None
        model = str(data.get("model") or self.model) if isinstance(data, dict) else self.model
        decision = decision_from_answers(
            answers,
            model=model,
            provider=self.provider,
            offered_operations=set(questions["operation"]["criteria"]),
        )
        if decision.operation == "BLOCKED" and decision.confidence == 0.0 and not decision.reason:
            decision.reason = "Jev chose an operation that is not available on this page."
        return decision


def goal_satisfied(goal: str, text: str) -> bool:
    """Offline stop condition used only by the fixture policy."""
    lowered_goal = goal.lower()
    lowered_text = text.lower()
    wants_price = "price" in lowered_goal or "$" in goal
    if wants_price and not _PRICE.search(text):
        return False
    keywords = [
        token
        for token in re.findall(r"[a-z0-9]{4,}", lowered_goal)
        if token not in _GENERIC
    ]
    if keywords and not any(token in lowered_text for token in keywords):
        return False
    if wants_price:
        return True
    return bool(keywords) and all(token in lowered_text for token in keywords[:3])


def _best_click(elements: list[Element], goal: str) -> Optional[Element]:
    tokens = set(re.findall(r"[a-z0-9]{3,}", goal.lower())) - _GENERIC
    clicks = [element for element in elements if element.kind == "click"]

    def score(element: Element) -> int:
        name = element.name.lower()
        return sum(1 for token in tokens if token in name)

    ranked = sorted(clicks, key=score, reverse=True)
    if ranked and score(ranked[0]) > 0:
        return ranked[0]
    return None


class FixturePolicy:
    """Deterministic stand-in so the browser loop can be demoed without a Jev key.

    It is not an evaluation model. ``symphony-browser`` uses it only when no
    Jev credential is configured, and every event records ``provider=fixture``.
    """

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
        if goal_satisfied(goal, observation.text):
            return Decision(
                operation="DONE",
                confidence=0.99,
                goal_met=True,
                goal_met_confidence=0.99,
                model=self.name,
                provider=self.provider,
                reason="The requested fact is visible on the page.",
            )
        typables = [element for element in observation.elements if element.kind == "type"]
        if typables and candidates:
            field = _preferred_field(typables)
            if field.value.strip() != candidates[0]:
                return Decision(
                    operation="TYPE_TEXT",
                    confidence=0.9,
                    type_target=field.index,
                    type_value=candidates[0],
                    model=self.name,
                    provider=self.provider,
                )
        if typables and typables[0].value.strip():
            button = _submit_button(observation.elements)
            if button is not None:
                return Decision(
                    operation="CLICK",
                    confidence=0.9,
                    click_target=button.index,
                    model=self.name,
                    provider=self.provider,
                )
            return Decision(
                operation="PRESS_ENTER",
                confidence=0.86,
                type_target=typables[0].index,
                model=self.name,
                provider=self.provider,
            )
        click = _best_click(observation.elements, goal)
        if click is not None:
            return Decision(
                operation="CLICK",
                confidence=0.88,
                click_target=click.index,
                model=self.name,
                provider=self.provider,
            )
        scrolled = sum(1 for item in history if item.get("operation") == "SCROLL_DOWN")
        if scrolled >= 2:
            return Decision(
                operation="BLOCKED",
                confidence=0.8,
                model=self.name,
                provider=self.provider,
                reason="No control on this page matches the goal.",
            )
        return Decision(
            operation="SCROLL_DOWN",
            confidence=0.7,
            model=self.name,
            provider=self.provider,
        )


def _preferred_field(fields: list[Element]) -> Element:
    for field in fields:
        if re.search(r"search|query|q\b|email|destination|from|to", field.name, re.IGNORECASE):
            return field
    return fields[0]


def _submit_button(elements: list[Element]) -> Optional[Element]:
    for element in elements:
        if element.kind == "click" and re.search(
            r"search|go|submit|find|next|continue", element.name, re.IGNORECASE
        ):
            return element
    return None


def jev_credentials() -> Optional[tuple[str, str, str]]:
    """Return ``(provider, api_key, model)`` or None.

    Vercel AI Gateway wins when several keys are set, because that is how
    the rest of Symphony already calls ``typesafe-ai/jev``. Set
    ``SYMPHONY_JEV_PROVIDER`` to ``vercel``, ``typesafe``, or ``openrouter``
    to override.
    """
    explicit = (os.environ.get("SYMPHONY_JEV_PROVIDER") or "").strip().lower()
    typesafe = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    gateway = (
        os.environ.get("AI_GATEWAY_API_KEY")
        or os.environ.get("VERCEL_AI_GATEWAY_API_KEY")
        or ""
    ).strip()
    openrouter = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    requested = (os.environ.get("JEV_MODEL") or "").strip()

    def vercel() -> tuple[str, str, str]:
        return ("vercel", gateway, requested or VERCEL_MODEL)

    def safe() -> tuple[str, str, str]:
        return ("typesafe", typesafe, requested or "jev-latest")

    def router() -> tuple[str, str, str]:
        return ("openrouter", openrouter, requested or "~typesafe/jev-latest")

    if explicit == "vercel" and gateway:
        return vercel()
    if explicit == "typesafe" and typesafe:
        return safe()
    if explicit == "openrouter" and openrouter:
        return router()
    if gateway:
        return vercel()
    if typesafe:
        return safe()
    if openrouter:
        return router()
    return None


def build_jev_policy(
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    base_url: str = "",
) -> JevPolicy:
    found = jev_credentials()
    if found is None:
        raise DecisionError(
            "Jev credentials missing. Set AI_GATEWAY_API_KEY (typesafe-ai/jev on "
            "Vercel AI Gateway), TYPESAFE_API_KEY, or OPENROUTER_API_KEY."
        )
    provider, api_key, model = found
    if provider == "vercel":
        client: Any = VercelJevClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            transport=transport,
        )
    elif provider == "typesafe":
        url = (os.environ.get("TYPESAFE_BASE_URL") or TYPESAFE_URL).strip()
        client = DirectJevClient(
            api_key=api_key,
            url=base_url or url,
            model=model,
            provider=provider,
            transport=transport,
        )
    else:
        url = (os.environ.get("OPENROUTER_DECISIONS_URL") or OPENROUTER_URL).strip()
        client = DirectJevClient(
            api_key=api_key,
            url=base_url or url,
            model=model,
            provider=provider,
            transport=transport,
        )
    return JevPolicy(client, model=model, provider=provider)


def build_policy(
    mode: str = "auto",
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    base_url: str = "",
) -> Policy:
    """``jev`` requires a key. ``fixture`` is the offline loop. ``auto`` prefers Jev."""
    selected = (mode or "auto").strip().lower()
    if selected == "fixture":
        return FixturePolicy()
    if selected not in {"auto", "jev"}:
        raise DecisionError(f"unknown policy {mode!r}")
    try:
        return build_jev_policy(transport=transport, base_url=base_url)
    except DecisionError:
        if selected == "jev":
            raise
        return FixturePolicy()


def candidates_for(goal: str) -> list[str]:
    return text_candidates(goal)


__all__ = [
    "OPENROUTER_URL",
    "TYPESAFE_URL",
    "VERCEL_MODEL",
    "DecisionError",
    "DirectJevClient",
    "FixturePolicy",
    "JevPolicy",
    "Policy",
    "VercelJevClient",
    "build_jev_policy",
    "build_policy",
    "candidates_for",
    "decision_from_answers",
    "goal_satisfied",
    "jev_credentials",
]
