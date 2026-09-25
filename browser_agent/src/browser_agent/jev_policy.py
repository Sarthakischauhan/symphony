"""Jev is the policy. A chat model is not asked which element to click."""

from __future__ import annotations

from typing import Any, Protocol

from browser_agent.fixture_policy import FixturePolicy
from browser_agent.jev_answers import DecisionError, decision_from_answers
from browser_agent.jev_client import JevClient, JevClientProtocol
from browser_agent.jev_credentials import resolve_jev_endpoint
from browser_agent.jev_questions import build_questions, build_state
from browser_agent.models import Decision, Observation


class Policy(Protocol):
    """Chooses the next Decision for one observed page."""

    name: str
    provider: str

    async def choose(
        self,
        *,
        goal: str,
        observation: Observation,
        history: list[dict[str, Any]],
        candidates: list[str],
    ) -> Decision: ...


class JevPolicy:
    """Primary policy: one evaluation call picks the operation and the target."""

    def __init__(self, client: JevClientProtocol, *, model: str, provider: str) -> None:
        self.client = client
        self.name = model
        self.provider = provider

    async def choose(
        self,
        *,
        goal: str,
        observation: Observation,
        history: list[dict[str, Any]],
        candidates: list[str],
    ) -> Decision:
        """Ask Jev once and reduce its answers to a Decision."""
        questions = build_questions(observation, goal, candidates)
        data = await self.client.complete(build_state(goal, observation, history), questions)
        return decision_from_answers(
            data.get("answers"),
            model=str(data.get("model") or self.name),
            provider=self.provider,
            offered_operations=set(questions["operation"]["criteria"]),
        )


def build_policy(mode: str = "auto") -> Policy:
    """Return the policy for ``mode``.

    ``fixture`` is the offline loop. ``jev`` needs a Jev key and raises
    DecisionError without one. ``auto`` uses Jev when a key is set and falls
    back to FixturePolicy when none is; a bad ``SYMPHONY_JEV_PROVIDER`` still raises.
    """
    selected = mode.strip().lower()
    if selected == "fixture":
        return FixturePolicy()
    if selected not in {"auto", "jev"}:
        raise DecisionError(f"unknown policy {mode!r}")
    endpoint = resolve_jev_endpoint()
    if endpoint is not None:
        return JevPolicy(JevClient.for_endpoint(endpoint), model=endpoint.model, provider=endpoint.provider)
    if selected == "jev":
        raise DecisionError(
            "Jev credentials missing. Set AI_GATEWAY_API_KEY (typesafe-ai/jev on "
            "Vercel AI Gateway), TYPESAFE_API_KEY, or OPENROUTER_API_KEY."
        )
    return FixturePolicy()


__all__ = ["JevPolicy", "Policy", "build_policy"]
