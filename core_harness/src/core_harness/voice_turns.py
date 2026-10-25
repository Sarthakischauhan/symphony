"""Harness turns on a live voice session: the link a run reaches by session id, and the model
call that sends a turn to it and maps its response back to StreamEvents.

core_ai.voice only speaks the model protocol; what the session has been told, and which run
owns a response, is kept here.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from core_ai.content import text_from_content
from core_ai.types import Message, StreamEvent
from core_ai.models.registry import ModelCatalog
from core_ai.voice import ResponseDone, TextDelta, ToolCall, VoiceSession, voice_catalog
from pydantic import BaseModel

from core_harness.addons.addon import Addon
from core_harness.model_call import ModelCall


@dataclass(eq=False)
class VoiceLink:
    """A voice session opened for one harness session, and what it has already been told.

    ``heard`` holds transcripts of speech the session took in as audio; the host adds each
    one to ``heard`` so the run answering it does not send the words again.
    """

    model_id: str
    session: VoiceSession
    synced: bool = False
    heard: List[str] = field(default_factory=list)


class VoiceLinks:
    """Open voice links by harness session id. The host owns one and hands each run its link
    through ``VoiceTurns``; there is no process-wide registry."""

    def __init__(self) -> None:
        self._links: Dict[str, VoiceLink] = {}

    def open(self, session_id: str, model_id: str, session: VoiceSession) -> VoiceLink:
        link = VoiceLink(model_id, session)
        self._links[session_id] = link
        return link

    def close(self, session_id: str, link: VoiceLink) -> None:
        if self._links.get(session_id) is link:
            del self._links[session_id]

    def get(self, session_id: str) -> Optional[VoiceLink]:
        return self._links.get(session_id)


class VoiceSessionNotOpen(LookupError):
    """A realtime model was run for a session with no open voice connection to it."""


class _ToolCallFunction(BaseModel):
    name: str
    arguments: str = "{}"


class _HistoryToolCall(BaseModel):
    """One entry of ``Message.tool_calls`` (the OpenAI-style shape the harness records)."""

    id: str
    function: _ToolCallFunction


class VoiceModelCall:
    """Sends only what the voice session has not seen, then maps its response to StreamEvents.

    Speech the session already heard (and, with server VAD, already answered) is not sent again.
    The first call on a fresh session replays the earlier history (text, tool calls and their
    results) so the harness history, already compacted by the turn's ``maybe_compact_turn``
    hook as for any model, stays the source of truth across reconnects and model swaps.
    """

    def __init__(self, link: VoiceLink) -> None:
        self.link = link
        self.session = link.session

    async def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        del model_id, max_output_tokens, reasoning_effort, extra_headers
        await self._configure(messages, tools or [])
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

    async def _configure(self, messages: List[Message], tools: List[Dict[str, Any]]) -> None:
        instructions = "\n\n".join(text_from_content(m.content) for m in messages if m.role == "system")
        config = replace(self.session.config, instructions=instructions, tools=tuple(tools))
        if config != self.session.config:
            await self.session.update(config)

    async def _send_turn(self, messages: List[Message]) -> None:
        conversation = [m for m in messages if m.role != "system"]
        new = _trailing_turn(conversation)
        link = self.link
        if not link.synced:
            for message in conversation[: len(conversation) - len(new)]:
                await self._replay(message)
            link.synced = True
        if new and new[0].role == "tool":
            for message in new:
                await self.session.add_tool_result(str(message.tool_call_id), text_from_content(message.content))
        elif new:
            text = text_from_content(new[0].content)
            if text in link.heard:
                link.heard.remove(text)
                if self.session.config.turn_detection == "server_vad":
                    return  # the session heard this speech and is already answering it
            else:
                await self.session.add_message("user", text)
        await self.session.respond()

    async def _replay(self, message: Message) -> None:
        text = text_from_content(message.content)
        if message.role == "tool":
            await self.session.add_tool_result(str(message.tool_call_id), text)
            return
        if message.role in ("user", "assistant") and text:
            await self.session.add_message(message.role, text)
        for call in message.tool_calls or []:
            parsed = _HistoryToolCall.model_validate(call)
            await self.session.add_tool_call(parsed.id, parsed.function.name, parsed.function.arguments)


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


class VoiceRouter:
    """The harness model call while ``VoiceTurns`` is attached: voice models stream from the
    run's open link, every other model from ``text`` (so a mid-session model switch works both
    ways on the same harness)."""

    def __init__(self, text: ModelCall, link: Optional[VoiceLink], catalog: ModelCatalog) -> None:
        self.text = text
        self.link = link
        self.catalog = catalog

    def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        provider, _, name = model_id.partition(":")
        if self.catalog.get(provider, name) is None:
            return self.text.stream(model_id, messages, tools or [], max_output_tokens, reasoning_effort, extra_headers)
        if self.link is None or self.link.model_id != model_id:
            raise VoiceSessionNotOpen(f"{model_id} is a voice model and this run has no open voice session for it")
        return VoiceModelCall(self.link).stream(model_id, messages, tools)


class VoiceTurns(Addon):
    """Routes a run's voice-model turns to its voice link by setting the harness model call.

    The host builds one per run (e.g. a core_server ``addon_factories`` entry) with that run's
    link, or None when the session has no voice connection open.
    """

    name = "voice_turns"

    def __init__(self, link: Optional[VoiceLink], catalog: ModelCatalog = voice_catalog) -> None:
        self.link = link
        self.catalog = catalog

    def attach(self, harness: Any) -> None:
        harness.model_call = VoiceRouter(harness.model_call or harness.registry, self.link, self.catalog)
