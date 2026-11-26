"""Run with the checkout's Python and installed workspace packages."""

import asyncio
import statistics
import tempfile
import time

from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
from core_harness import CoreHarness, HarnessConfig, Tool
from coding_agent.addons.persistence.jsonl import JsonlPersistence


def history(count):
    return [
        message
        for index in range(count)
        for message in (
            Message(
                role="assistant",
                content="",
                tool_calls=[{"id": str(index), "type": "function", "function": {"name": "read", "arguments": "{}"}}],
            ),
            Message(role="tool", content="data " * 100, tool_call_id=str(index)),
        )
    ]


def measure(name, operation):
    operation()
    samples = []
    for _ in range(9):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start) * 1000)
    print(f"{name}: median {statistics.median(samples):.3f} ms")


async def restore_lag(root, messages):
    await JsonlPersistence(root).save_conversation(session_id="bench", messages=messages)
    samples = []
    totals = []
    for _ in range(9):
        store = JsonlPersistence(root)
        start = time.perf_counter()
        task = asyncio.create_task(store.load_resume(session_id="bench"))
        await asyncio.sleep(0)
        samples.append((time.perf_counter() - start) * 1000)
        transcript, context = await task
        totals.append((time.perf_counter() - start) * 1000)
        assert transcript == context == messages
    print(f"Cold resume first yield: median {statistics.median(samples):.3f} ms")
    print(f"Cold resume total: median {statistics.median(totals):.3f} ms")


class MockModel:
    def __init__(self, *, tool_calls: bool) -> None:
        self.tool_calls = tool_calls

    async def stream(self, model_id, messages, tools):
        if self.tool_calls:
            self.tool_calls = False
            for index, delay_ms in enumerate((100, 10, 100, 10)):
                yield StreamEvent(
                    type="toolcall_start",
                    content_index=index,
                    tool_call_id=str(index),
                    tool_name="pause",
                )
                yield StreamEvent(type="toolcall_delta", content_index=index, delta=f'{{"delay_ms": {delay_ms}}}')
        else:
            for _ in range(1 if tools else 4000):
                yield StreamEvent(type="text_delta", delta="x")
        yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
        yield StreamEvent(type="done")


async def bench_loop(tool_calls: bool) -> None:
    async def pause(delay_ms: int) -> str:
        await asyncio.sleep(delay_ms / 1000)
        return str(delay_ms)

    samples = []
    for _ in range(10):
        harness = CoreHarness(
            registry=MockModel(tool_calls=tool_calls),
            model_id="bench:mock",
            system_prompt="Benchmark",
            tools=[Tool(pause, parallel=True)] if tool_calls else [],
            config=HarnessConfig(max_runtime_seconds=30, max_parallel_tool_calls=2),
        )
        start = time.perf_counter()
        result = await harness.run("Benchmark")
        assert result.output_text == "x" * (1 if tool_calls else 4000)
        samples.append((time.perf_counter() - start) * 1000)
    label = "Mixed-duration parallel tools" if tool_calls else "Deadline-enabled stream (4,000 deltas)"
    print(f"{label}: median {statistics.median(samples[1:]):.3f} ms")


if __name__ == "__main__":
    for count in (100, 1000, 4000):
        messages = history(count)
        measure(f"Chat ({count} calls)", lambda: OpenAIProvider._chat_messages(messages))
        measure(f"Responses ({count} calls)", lambda: OpenAIProvider._responses_input(messages))
    with tempfile.TemporaryDirectory() as root:
        asyncio.run(restore_lag(root, messages))
    asyncio.run(bench_loop(False))
    asyncio.run(bench_loop(True))
