"""Run a harness model turn on a live voice session instead of a text completion."""

from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any, Dict, List, Optional, Protocol

from core_ai.content import text_from_content
from core_ai.models import get_model
from core_ai.types import Message, StreamEvent
from core_ai.voice.session import ResponseDone, TextDelta, ToolCall, VoiceSession
from core_ai.voice.sessions import voice_sessions


class ModelCall(Protocol):
    """The model-turn interface the harness streams from; ``ModelRegistry`` satisfies it."""

    def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]: ...


class VoiceSessionNotOpen(LookupError):
    """A realtime model was run for a session with no open voice connection."""


class VoiceModelCall:
    """Sends only what the voice session has not seen, then maps its response to StreamEvents.

    Speech the session already heard (and, with server VAD, already answered) is not sent again.
    The first call on a fresh session replays the earlier text turns so the harness history stays
    the source of truth across reconnects and model swaps.
    """

    def __init__(self, session: VoiceSession) -> None:
        self.session = session

    async def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        del model_id, max_output_tokens, reasoning_effort, extra_headers
        await self._configure(messages, tools)
        await self._send_turn(messages)
        index = 0
        async for event in self.session.response():
            if isinstance(event, TextDelta):
                yield StreamEvent(type="text_delta", delta=event.text)
            elif isinstance(event, ToolCall):
                yield StreamEvent(
                    type="toolcall_start",
                    content_index=index,
                    tool_call_id=event.call_id,
                    tool_name=event.name,
                )
                yield StreamEvent(
                    type="toolcall_arguments",
                    content_index=index,
                    tool_call_id=event.call_id,
                    delta=event.arguments,
                )
                index += 1
            elif isinstance(event, ResponseDone):
                if event.error:
                    raise RuntimeError(f"voice response failed: {event.error}")
                if event.input_tokens is not None or event.output_tokens is not None:
                    yield _usage_event(event)
                yield StreamEvent(type="done")

    async def _configure(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> None:
        instructions = "\n\n".join(
            text_from_content(m.content) for m in messages if m.role == "system"
        )
        config = replace(
            self.session.config, instructions=instructions, tools=tuple(tools)
        )
        if config != self.session.config:
            await self.session.update(config)

    async def _send_turn(self, messages: List[Message]) -> None:
        conversation = [m for m in messages if m.role != "system"]
        new = _trailing_turn(conversation)
        history = self.session.history
        if not history.synced:
            for message in conversation[: len(conversation) - len(new)]:
                await self._replay(message)
            history.synced = True
        if new and new[0].role == "tool":
            for message in new:
                await self.session.add_tool_result(
                    str(message.tool_call_id), text_from_content(message.content)
                )
        elif new:
            text = text_from_content(new[0].content)
            if text in history.heard:
                history.heard.remove(text)
                if self.session.config.turn_detection == "server_vad":
                    return  # the session heard this speech and is already answering it
            else:
                await self.session.add_message("user", text)
        await self.session.respond()

    async def _replay(self, message: Message) -> None:
        text = text_from_content(message.content)
        if message.role in ("user", "assistant") and text:
            await self.session.add_message(message.role, text)


def _trailing_turn(conversation: List[Message]) -> List[Message]:
    """The messages this call answers: trailing tool results, or the last user message."""
    tools: List[Message] = []
    for message in reversed(conversation):
        if message.role != "tool":
            break
        tools.insert(0, message)
    if tools:
        return tools
    return conversation[-1:] if conversation and conversation[-1].role == "user" else []


def _usage_event(done: ResponseDone) -> StreamEvent:
    prompt = done.input_tokens or 0
    completion = done.output_tokens or 0
    return StreamEvent(
        type="usage",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def voice_model_call(
    model_id: str, session_id: Optional[str]
) -> Optional[VoiceModelCall]:
    """The model call for a realtime model's open session; None for every other model."""
    provider, _, name = model_id.partition(":")
    info = get_model(provider, name)
    if info is None or info.api != "realtime":
        return None
    session = voice_sessions.get(session_id) if session_id else None
    if session is None:
        raise VoiceSessionNotOpen(
            f"{model_id} is a realtime model: open a voice session for "
            f"session {session_id!r} with ModelRegistry.open_voice before running it"
        )
    return VoiceModelCall(session)
