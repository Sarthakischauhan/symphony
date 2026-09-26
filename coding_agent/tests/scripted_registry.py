"""Mock provider that replays scripted tool-call turns (no network)."""

from __future__ import annotations

import asyncio
import json

from core_ai.content import text_from_content
from core_ai.types import Message, StreamEvent

from coding_agent.compaction.prompts import COMPACTION_SYSTEM_PROMPT

Turn = list[tuple[str, dict]]


def first_user_text(messages: list[Message]) -> str:
    return next(
        (
            text_from_content(m.content)
            for m in messages
            if m.role == "user" and not text_from_content(m.content).startswith("[compacted")
        ),
        "",
    )


class ScriptedRegistry:
    """Keyed by the conversation's first user prompt; each call for a key plays its next turn."""

    def __init__(self, scripts: dict[str, list[Turn]], *, delay: float = 0.0) -> None:
        self.scripts = scripts
        self.delay = delay
        self.calls: list[list[Message]] = []
        self.steps: dict[str, int] = {}

    async def stream(self, model_id, messages, tools=None, **kwargs):
        del model_id, tools, kwargs
        if messages and messages[0].content == COMPACTION_SYSTEM_PROMPT:
            yield StreamEvent(type="text_delta", delta="- summary of dropped turns")
            yield StreamEvent(type="done")
            return
        self.calls.append(list(messages))
        if self.delay:
            await asyncio.sleep(self.delay)
        key = first_user_text(messages)
        turns = self.scripts.get(key, [])
        step = self.steps[key] = self.steps.get(key, -1) + 1
        if step < len(turns):
            for index, (name, args) in enumerate(turns[step]):
                call_id = f"call-{step}-{index}-{len(self.calls)}"
                yield StreamEvent(type="toolcall_start", content_index=index, tool_call_id=call_id, tool_name=name)
                yield StreamEvent(type="toolcall_delta", content_index=index, delta=json.dumps(args))
        else:
            yield StreamEvent(type="text_delta", delta="all done")
        yield StreamEvent(type="done")
