import asyncio

import pytest
from core_ai.models import ModelInfo, ModelPrice, register_model, unregister_model
from core_ai.types import StreamEvent
from core_harness.loop.stream import dispatch_stream_event
from core_harness.models import StreamedTurn, UsageTotals


def test_usage_cost_bills_cached_input_at_the_cache_rates() -> None:
    """The footer's session_cost prices cache reads and writes at their rates."""
    register_model(
        ModelInfo(
            id="priced-footer",
            provider="anthropic",
            api="messages",
            price=ModelPrice(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        )
    )

    async def run() -> list[tuple[str, dict]]:
        emitted: list[tuple[str, dict]] = []

        async def emit(event_type: str, payload: dict) -> None:
            emitted.append((event_type, payload))

        # 1M prompt tokens: 600k read from cache, 100k written, 300k fresh.
        event = StreamEvent(
            type="usage",
            prompt_tokens=1_000_000,
            completion_tokens=100_000,
            total_tokens=1_100_000,
            cache_read_tokens=600_000,
            cache_write_tokens=100_000,
        )
        await dispatch_stream_event(
            event,
            turn=0,
            usage=UsageTotals(),
            streamed=StreamedTurn(estimated_message_tokens=0),
            emit=emit,
            model_id="anthropic:priced-footer",
        )
        return emitted

    try:
        [(name, payload)] = asyncio.run(run())
    finally:
        unregister_model("anthropic", "priced-footer")
    assert name == "usage"
    assert payload["session_cost"] == pytest.approx(0.3 * 3.0 + 0.1 * 15.0 + 0.6 * 0.3 + 0.1 * 3.75)
