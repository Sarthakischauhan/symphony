import asyncio

from core_ai.types import StreamEvent
from core_harness.loop.stream import dispatch_stream_event
from core_harness.models import StreamedTurn, UsageTotals


def test_reasoning_summaries_restart_after_text_and_tool_calls() -> None:
    async def run() -> list[tuple[str, dict]]:
        emitted = []

        async def emit(event_type, payload):
            emitted.append((event_type, payload))

        streamed = StreamedTurn(estimated_message_tokens=0)
        usage = UsageTotals()
        for event in [
            StreamEvent(type="reasoning_delta", delta="first"),
            StreamEvent(type="text_delta", delta="answer"),
            StreamEvent(type="reasoning_delta", delta="second"),
            StreamEvent(type="toolcall_start", tool_name="read"),
            StreamEvent(type="reasoning_delta", delta="third"),
        ]:
            await dispatch_stream_event(event, turn=0, usage=usage, streamed=streamed, emit=emit)
        return emitted

    events = asyncio.run(run())
    assert [payload["text"] for name, payload in events if name == "reasoning_delta"] == [
        "first", "second", "third"
    ]
