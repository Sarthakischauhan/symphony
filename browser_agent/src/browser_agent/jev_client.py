"""One HTTP client for every Jev endpoint. Only the URL, headers, and body shape differ.

Vercel AI Gateway takes the shared ``core_ai`` evaluation-model body. TypeSafe
``/v1/systemone`` and OpenRouter ``/api/alpha/decisions`` take the questions
directly, with yes/no questions typed ``noul``.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Protocol

import httpx

from core_ai.providers.vercel_evaluation import evaluation_request_body, evaluation_request_headers
from core_ai.types import Message

from browser_agent.jev_answers import DecisionError
from browser_agent.jev_credentials import JevEndpoint
from browser_agent.jev_questions import for_noul_api

BodyBuilder = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class JevClientProtocol(Protocol):
    """Anything that answers one Jev request; tests pass a scripted fake."""

    async def complete(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]: ...


class JevClient:
    """POST ``body(state, questions)`` to ``url`` and return the JSON object."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        body: BodyBuilder,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.url = url
        self.headers = headers
        self.body = body
        self.transport = transport

    @classmethod
    def for_endpoint(cls, endpoint: JevEndpoint, transport: Optional[httpx.AsyncBaseTransport] = None) -> JevClient:
        """The Vercel evaluation-model shape for ``vercel``; the direct decisions shape otherwise."""
        if endpoint.provider == "vercel":
            return cls(
                endpoint.url,
                evaluation_request_headers(endpoint.model, api_key=endpoint.api_key),
                lambda state, questions: evaluation_request_body(
                    [Message(role="user", content=json.dumps({"state": state, "questions": questions}))]
                ),
                transport,
            )
        headers = {
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return cls(
            endpoint.url,
            headers,
            lambda state, questions: {"model": endpoint.model, "state": state, "questions": for_noul_api(questions)},
            transport,
        )

    async def complete(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        """Send one request. Raises DecisionError when the reply is not a JSON object."""
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.post(self.url, json=self.body(state, questions), headers=self.headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise DecisionError("Jev returned a non-object response")
        return data


__all__ = ["JevClient", "JevClientProtocol"]
