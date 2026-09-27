"""Browser agent built on core_harness."""

from __future__ import annotations

from typing import Optional

from core_ai.providers.catalog import MissingProviderCredentials
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.registry import ModelRegistry
from core_harness import CoreHarness, EventSink, HarnessConfig
from core_harness.errors import HarnessLimitExceeded

from browser_agent.models import BrowserRunResult, RunStatus
from browser_agent.prompts import SYSTEM_PROMPT
from browser_agent.session import PageSession
from browser_agent.tools import browser_tools


class BrowserAgent:
    """One goal, one page, driven by ``CoreHarness.run``."""

    def __init__(
        self,
        *,
        registry: Optional[ModelRegistry] = None,
        model_id: str = "",
        max_steps: int = 12,
        sink: Optional[EventSink] = None,
    ) -> None:
        """``max_steps`` is the harness turn cap. ``sink`` collects every event.

        An empty registry is allowed and leaves ``model_id`` empty; ``run`` then
        ends as ``error`` without calling the harness. A missing provider key
        still raises ``MissingProviderCredentials`` here.
        """
        self.registry = registry if registry is not None else build_default_registry()
        self.model_id = model_id
        if not self.model_id and self.registry.namespaces():
            self.model_id = default_model_id(self.registry)
        self.max_steps = max_steps
        self.sink = sink or EventSink()

    async def run(self, goal: str, session: PageSession) -> BrowserRunResult:
        """Give ``goal`` to the harness. The model's last message is the answer.

        Never raises: a missing model or a failed run ends as ``status="error"``.
        Hitting the turn cap ends as ``limited``.
        """
        if not self.model_id:
            return BrowserRunResult(status="error", goal=goal, message=str(MissingProviderCredentials()))
        provider, _, model = self.model_id.partition(":")
        harness = CoreHarness(
            registry=self.registry,
            model_id=self.model_id,
            system_prompt=SYSTEM_PROMPT,
            config=HarnessConfig(max_turns=self.max_steps),
            tools=browser_tools(session),
            sink=self.sink,
            agent_id="browser",
        )
        try:
            result = await harness.run(goal)
        except HarnessLimitExceeded as exc:
            return _result("limited", goal, provider, model, message=str(exc))
        except Exception as exc:
            return _result("error", goal, provider, model, message=str(exc))
        if result.output_text.strip():
            return _result("done", goal, provider, model, output_text=result.output_text)
        return _result("blocked", goal, provider, model, message="The model stopped without an answer.")


def _result(
    status: RunStatus,
    goal: str,
    provider: str,
    model: str,
    *,
    output_text: str = "",
    message: str = "",
) -> BrowserRunResult:
    return BrowserRunResult(
        status=status, output_text=output_text, goal=goal, model=model, provider=provider, message=message
    )


__all__ = ["BrowserAgent"]
