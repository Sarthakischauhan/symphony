"""Shutting the agent down closes its providers' pooled connections."""

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from core_ai.providers.base import BaseProvider
from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent

from coding_agent.agent import CodingAgent


class ClosingProvider(BaseProvider):
    def __init__(self) -> None:
        self.closed = 0

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        yield StreamEvent(type="done")

    async def aclose(self) -> None:
        self.closed += 1


def test_shutdown_closes_every_provider(tmp_path: Path) -> None:
    registry = ModelRegistry()
    first, second = ClosingProvider(), ClosingProvider()
    registry.register("first", first)
    registry.register("second", second)
    agent = CodingAgent(registry=registry, model_id="first:model", workspace=tmp_path)

    asyncio.run(agent.shutdown())

    assert (first.closed, second.closed) == (1, 1)
