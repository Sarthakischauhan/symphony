"""Evaluator implementations. Vercel helpers are reused, not forked."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

from core_ai.providers.catalog import find_provider, provider_api_key
from core_ai.providers.vercel import (
    evaluation_model_url,
    evaluation_request_body,
    evaluation_request_headers,
    is_evaluation_model,
)
from core_ai.types import Message

from coding_agent.config import EvaluationConfig
from coding_agent.evaluation.protocol import (
    EvaluationDecision,
    EvaluationPhase,
    EvaluationResult,
    FINISH_QUESTIONS,
    START_QUESTIONS,
    error_result,
    findings_from_decisions,
    skipped_result,
)
from coding_agent.evaluation.state import RunState, clip_text

logger = logging.getLogger(__name__)

RATIONALE_MAX_CHARS = 280


def vercel_credentials(config: EvaluationConfig) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` for the configured evaluation provider."""
    spec = find_provider(config.provider)
    api_key = provider_api_key(spec) if spec is not None else ""
    env_base = (os.environ.get("AI_GATEWAY_BASE_URL") or "").strip()
    default_base = (spec.default_base_url or "").strip() if spec is not None else ""
    return (api_key or "", env_base or default_base)


def decision_from_answer(name: str, answer: object) -> EvaluationDecision:
    if not isinstance(answer, dict):
        return EvaluationDecision(
            name=name,
            kind="error",
            label="invalid",
            rationale="answer was not an object",
        )
    kind = str(answer.get("type") or "").strip() or "error"
    rationale = clip_text(
        str(answer.get("rationale") or answer.get("reason") or answer.get("explanation") or ""),
        RATIONALE_MAX_CHARS,
    )
    if kind == "boolean":
        probability = answer.get("probability")
        probs: Optional[dict[str, float]] = None
        if isinstance(probability, (int, float)):
            true_p = float(probability)
            probs = {"true": true_p, "false": float(1.0 - true_p)}
            value = true_p >= 0.5
        else:
            value = bool(answer.get("value"))
        return EvaluationDecision(
            name=name,
            kind="boolean",
            value=value,
            probs=probs,
            label="true" if value else "false",
            rationale=rationale,
        )
    if kind == "choice":
        choice = str(answer.get("choice") or "").strip()
        return EvaluationDecision(
            name=name,
            kind="choice",
            value=choice,
            label=choice,
            rationale=rationale,
        )
    if kind == "score":
        score = answer.get("score")
        return EvaluationDecision(
            name=name,
            kind="score",
            value=score,
            label="" if score is None else str(score),
            rationale=rationale,
        )
    return EvaluationDecision(
        name=name,
        kind="error",
        value=answer,
        label=kind or "invalid",
        rationale=rationale or "unsupported answer type",
    )


def result_from_answers(phase: EvaluationPhase, answers: object) -> EvaluationResult:
    if not isinstance(answers, dict) or not answers:
        return skipped_result(phase, "evaluation model returned no answers")
    decisions = [decision_from_answer(str(name), answer) for name, answer in answers.items()]
    return EvaluationResult(
        phase=phase,
        status="ok",
        decisions=decisions,
        findings=findings_from_decisions(decisions),
    )


class StubEvaluator:
    """Offline evaluator: records nothing and returns skipped."""

    async def on_start(self, state: RunState) -> EvaluationResult:
        del state
        return skipped_result("start", "stub evaluator")

    async def on_finish(self, state: RunState) -> EvaluationResult:
        del state
        return skipped_result("finish", "stub evaluator")


class MockEvaluator:
    """Test double that records each start/finish call."""

    def __init__(
        self,
        *,
        start: Optional[EvaluationResult] = None,
        finish: Optional[EvaluationResult] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.start_result = start
        self.finish_result = finish
        self.error = error
        self.starts: list[RunState] = []
        self.finishes: list[RunState] = []

    async def on_start(self, state: RunState) -> EvaluationResult:
        self.starts.append(state)
        if self.error is not None:
            raise self.error
        return self.start_result or skipped_result("start", "mock")

    async def on_finish(self, state: RunState) -> EvaluationResult:
        self.finishes.append(state)
        if self.error is not None:
            raise self.error
        return self.finish_result or skipped_result("finish", "mock")


class LLMEvaluator:
    """Placeholder chat-model critic. Not wired; Jev never becomes the primary model."""

    async def on_start(self, state: RunState) -> EvaluationResult:
        del state
        return skipped_result("start", "LLMEvaluator is a stub; use VercelJevEvaluator")

    async def on_finish(self, state: RunState) -> EvaluationResult:
        del state
        return skipped_result("finish", "LLMEvaluator is a stub; use VercelJevEvaluator")


class VercelJevEvaluator:
    """POST ``/v4/ai/evaluation-model`` using core_ai Vercel helpers."""

    def __init__(
        self,
        config: EvaluationConfig,
        *,
        api_key: str = "",
        base_url: str = "",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.config = config
        resolved_key, resolved_base = vercel_credentials(config)
        self.api_key = api_key or resolved_key
        self.base_url = base_url or resolved_base
        self.transport = transport

    async def on_start(self, state: RunState) -> EvaluationResult:
        return await self._evaluate("start", state, START_QUESTIONS)

    async def on_finish(self, state: RunState) -> EvaluationResult:
        return await self._evaluate("finish", state, FINISH_QUESTIONS)

    async def _evaluate(
        self,
        phase: EvaluationPhase,
        state: RunState,
        questions: dict[str, Any],
    ) -> EvaluationResult:
        if self.config.on_error != "fail-open":
            return skipped_result(phase, "unsupported on_error policy")
        if not self.api_key:
            return skipped_result(phase, "missing Vercel AI Gateway API key")
        model = self.config.model
        if not is_evaluation_model(model):
            return error_result(phase, f"{model} is not an evaluation model")
        payload = {"state": state.as_eval_state(), "questions": questions}
        body = evaluation_request_body(
            [Message(role="user", content=json.dumps(payload))]
        )
        try:
            async with httpx.AsyncClient(transport=self.transport) as client:
                response = await client.post(
                    evaluation_model_url(self.base_url),
                    json=body,
                    headers=evaluation_request_headers(model, api_key=self.api_key),
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("Jev evaluator %s failed open: %s", phase, exc)
            return error_result(phase, clip_text(str(exc), RATIONALE_MAX_CHARS))
        if not isinstance(data, dict):
            return error_result(phase, "evaluation model returned a non-object response")
        return result_from_answers(phase, data.get("answers"))


__all__ = [
    "LLMEvaluator",
    "MockEvaluator",
    "StubEvaluator",
    "VercelJevEvaluator",
    "decision_from_answer",
    "result_from_answers",
    "vercel_credentials",
]
