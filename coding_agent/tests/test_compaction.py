"""Model-backed compaction: summarizer, add-on, and the manual compact path."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from core_ai.types import Message, StreamEvent
from core_harness import CompactionAddon, CoreHarness, HarnessConfig, NullControlPlane
from core_harness.addons.compaction import KeepSystemRecentCompactor, TemplateTurnSummarizer
from core_harness.context import COMPACTED_CONTEXT_MARK, estimate_prompt_tokens

from coding_agent import CodingAgent
from coding_agent.agent import default_addons
from coding_agent.compaction import (
    AiCompactionAddon,
    ModelTurnSummarizer,
    ai_compaction_from_config,
    render_dropped_turns,
)
from coding_agent.compaction.prompts import COMPACTION_SYSTEM_PROMPT
from coding_agent.config import CodingAgentConfig, CompactionConfig, LearningConfig
from coding_agent.persistence import SqlitePersistence


class StubRegistry:
    """Returns one narrative per call and records what it was asked."""

    def __init__(self, narrative: str = "- fixed the retry helper\n- tests pass") -> None:
        self.narrative = narrative
        self.calls: list[dict[str, Any]] = []

    async def stream(self, model_id, messages, tools=None, max_output_tokens=None, **kwargs):
        self.calls.append(
            {
                "model_id": model_id,
                "messages": list(messages),
                "tools": tools,
                "max_output_tokens": max_output_tokens,
            }
        )
        yield StreamEvent(type="text_delta", delta=self.narrative)
        yield StreamEvent(type="done")


class FailingRegistry:
    async def stream(self, model_id, messages, tools=None, max_output_tokens=None, **kwargs):
        del model_id, messages, tools, max_output_tokens, kwargs
        raise RuntimeError("provider down")
        yield  # pragma: no cover


def _tool_group(call_id: str, name: str, result: str, *, path: str) -> list[Message]:
    return [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": f'{{"path": "{path}"}}'},
                }
            ],
        ),
        Message(role="tool", content=result, tool_call_id=call_id),
    ]


def _conversation() -> list[Message]:
    messages = [
        Message(role="system", content="system prompt"),
        Message(role="user", content="original task: fix retries"),
        Message(role="assistant", content="Looking."),
    ]
    for index, path in enumerate(("src/a.py", "src/b.py", "src/c.py")):
        messages.append(Message(role="user", content=f"follow-up {index}"))
        messages.extend(_tool_group(f"call-{index}", "read_file", "Z" * 120, path=path))
        messages.append(Message(role="assistant", content=f"ack {index}"))
    return messages


def _compact(compactor: KeepSystemRecentCompactor, messages: list[Message]) -> list[Message]:
    return asyncio.run(
        compactor.compact(
            messages,
            turn=0,
            context_limit=200_000,
            tokens_used=estimate_prompt_tokens(messages),
            context_left=None,
        )
    )


def test_model_summarizer_turns_dropped_history_into_one_marked_message() -> None:
    registry = StubRegistry()
    summarizer = ModelTurnSummarizer(registry=registry, model_id="fake:model", max_output_tokens=321)
    compactor = KeepSystemRecentCompactor(keep_recent=4, summarizer=summarizer)
    messages = _conversation()

    compacted = _compact(compactor, messages)

    assert compacted[0].content == "system prompt"
    assert compacted[1].content == "original task: fix retries"
    summary = compacted[2]
    assert summary.role == "user"
    text = str(summary.content)
    assert text.startswith(COMPACTED_CONTEXT_MARK)
    assert "- fixed the retry helper" in text
    assert "src/a.py" in text and "read_file" in text
    assert sum(str(m.content).startswith(COMPACTED_CONTEXT_MARK) for m in compacted) == 1

    recent = compacted[3:]
    assert [m.role for m in recent] == ["user", "assistant", "tool", "assistant"]
    assert recent[0].content == "follow-up 2"
    assert recent[1].tool_calls and recent[2].tool_call_id == "call-2"
    assert all(m.content != "follow-up 0" for m in compacted)

    assert len(registry.calls) == 1
    call = registry.calls[0]
    assert call["model_id"] == "fake:model"
    assert call["tools"] == []
    assert call["max_output_tokens"] == 321
    assert call["messages"][0].content == COMPACTION_SYSTEM_PROMPT
    transcript = str(call["messages"][1].content)
    assert "follow-up 0" in transcript and "src/b.py" in transcript
    assert "follow-up 2" not in transcript


def test_model_summarizer_keeps_tool_groups_atomic_at_window_edge() -> None:
    registry = StubRegistry()
    compactor = KeepSystemRecentCompactor(
        keep_recent=2,
        summarizer=ModelTurnSummarizer(registry=registry, model_id="fake:model"),
    )
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="task"),
        Message(role="assistant", content="old"),
        *_tool_group("call-x", "read_file", "body", path="x.py"),
        Message(role="assistant", content="done"),
    ]

    compacted = _compact(compactor, messages)

    # The 2-message tool group does not fit beside "done", so it is dropped whole
    # rather than split; the summary transcript still sees both halves.
    assert [m.role for m in compacted] == ["system", "user", "user", "assistant"]
    assert compacted[-1].content == "done"
    transcript = str(registry.calls[0]["messages"][1].content)
    assert "read_file" in transcript and "tool[read_file]: body" in transcript

    roomier = KeepSystemRecentCompactor(
        keep_recent=3,
        summarizer=ModelTurnSummarizer(registry=registry, model_id="fake:model"),
    )
    compacted = _compact(roomier, messages)
    assert [m.role for m in compacted] == ["system", "user", "user", "assistant", "tool", "assistant"]
    assert compacted[3].tool_calls and compacted[4].tool_call_id == "call-x"


def test_model_summarizer_follows_current_harness_model_id() -> None:
    registry = StubRegistry()
    current = {"model_id": "fake:first"}
    summarizer = ModelTurnSummarizer(registry=registry, model_id=lambda: current["model_id"])
    turns = [[Message(role="user", content="hello")]]

    asyncio.run(summarizer.summarize(turns, tokens=3))
    current["model_id"] = "fake:second"
    asyncio.run(summarizer.summarize(turns, tokens=3))

    assert [call["model_id"] for call in registry.calls] == ["fake:first", "fake:second"]


def test_model_summarizer_falls_back_to_template_when_model_fails() -> None:
    summarizer = ModelTurnSummarizer(registry=FailingRegistry(), model_id="fake:model")
    turns = [[Message(role="user", content="please fix the bug")]]

    message = asyncio.run(summarizer.summarize(turns, tokens=5))
    template = asyncio.run(TemplateTurnSummarizer().summarize(turns, tokens=5))

    assert message == template
    assert str(message.content).startswith(COMPACTED_CONTEXT_MARK)


def test_model_summarizer_falls_back_when_model_returns_nothing() -> None:
    summarizer = ModelTurnSummarizer(registry=StubRegistry(narrative="   "), model_id="fake:model")
    turns = [[Message(role="user", content="please fix the bug")]]

    message = asyncio.run(summarizer.summarize(turns, tokens=5))

    assert "Summary of the dropped work" not in str(message.content)
    assert 'User asks: "please fix the bug"' in str(message.content)


def test_render_dropped_turns_elides_middle_when_over_budget() -> None:
    turns = [[Message(role="user", content=f"line {index} " + "x" * 40)] for index in range(40)]

    transcript = render_dropped_turns(turns, max_chars=600)

    assert len(transcript) < 800
    assert "line 0 " in transcript
    assert "line 39 " in transcript
    assert "lines omitted" in transcript


def test_ai_compaction_addon_mounts_and_forks_with_same_settings() -> None:
    registry = StubRegistry()
    addon = AiCompactionAddon(
        keep_recent=3,
        target_tokens=5_000,
        keep_recent_tool_results=2,
        max_output_tokens=150,
        max_transcript_chars=1_000,
    )
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:parent",
        system_prompt="sys",
        config=HarnessConfig(),
        control_plane=NullControlPlane(),
        addons=[addon],
    )

    assert harness.state.compactor is addon.compactor
    assert isinstance(addon.compactor, KeepSystemRecentCompactor)
    assert addon.compactor.keep_recent == 3
    assert addon.compactor.target_tokens == 5_000
    assert addon.compactor.keep_recent_tool_results == 2
    assert isinstance(addon.summarizer, ModelTurnSummarizer)
    assert addon.summarizer.model_id == "fake:parent"
    harness.model_id = "fake:switched"
    assert addon.summarizer.model_id == "fake:switched"

    child = addon.fork_for_child(harness)
    assert isinstance(child, AiCompactionAddon) and child is not addon
    assert child.compactor is None
    child_harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:child",
        system_prompt="sys",
        config=HarnessConfig(),
        control_plane=NullControlPlane(),
        addons=[child],
    )
    assert child_harness.state.compactor is child.compactor
    assert child.compactor is not addon.compactor
    assert child.compactor.keep_recent == 3
    assert child.compactor.target_tokens == 5_000
    assert child.summarizer.max_output_tokens == 150
    assert child.summarizer.max_transcript_chars == 1_000
    assert child.summarizer.model_id == "fake:child"


def test_ai_compaction_addon_occupies_compaction_slot() -> None:
    harness = CoreHarness(
        registry=StubRegistry(),  # type: ignore[arg-type]
        model_id="fake:model",
        system_prompt="sys",
        config=HarnessConfig(),
        addons=[AiCompactionAddon()],
    )
    with pytest.raises(ValueError, match="duplicate addon name: 'compaction'"):
        harness.register_addon(CompactionAddon())


def test_default_addons_prefer_ai_compaction_and_honour_opt_out(tmp_path: Path) -> None:
    persistence = SqlitePersistence(tmp_path / "sessions.sqlite3")
    harness_config = HarnessConfig(compaction_keep_recent=6, context_target_tokens=9_000)

    ai_addons = default_addons(
        persistence=persistence,
        harness_config=harness_config,
        compaction=CompactionConfig(max_output_tokens=222),
        include_subagent=False,
    )
    template_addons = default_addons(
        persistence=persistence,
        harness_config=harness_config,
        compaction=CompactionConfig(ai_summary=False),
        include_subagent=False,
    )

    ai = next(addon for addon in ai_addons if addon.name == "compaction")
    assert isinstance(ai, AiCompactionAddon)
    assert ai.keep_recent == 6 and ai.target_tokens == 9_000 and ai.max_output_tokens == 222
    template = next(addon for addon in template_addons if addon.name == "compaction")
    assert isinstance(template, CompactionAddon)
    assert isinstance(template.compactor, KeepSystemRecentCompactor)
    assert isinstance(template.compactor.summarizer, TemplateTurnSummarizer)


def test_ai_compaction_from_config_reads_harness_and_summary_settings() -> None:
    addon = ai_compaction_from_config(
        HarnessConfig(compaction_keep_recent=4, context_target_tokens=1_234, tool_result_keep_recent=3),
        CompactionConfig(max_output_tokens=99, max_transcript_chars=555),
    )
    assert addon.keep_recent == 4
    assert addon.target_tokens == 1_234
    assert addon.keep_recent_tool_results == 3
    assert addon.max_output_tokens == 99
    assert addon.max_transcript_chars == 555


class RecordingCompactor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def compact(self, messages, *, turn, context_limit, tokens_used, context_left):
        self.calls.append(
            {
                "count": len(messages),
                "turn": turn,
                "context_limit": context_limit,
                "tokens_used": tokens_used,
                "context_left": context_left,
            }
        )
        return [messages[0], Message(role="user", content=f"{COMPACTED_CONTEXT_MARK} stub")]


def _agent(tmp_path: Path, registry: Any, **overrides: Any) -> CodingAgent:
    config = CodingAgentConfig(learning=LearningConfig(enabled=False))
    if overrides:
        config = config.model_copy(update={"harness": config.harness.model_copy(update=overrides)})
    return CodingAgent(
        registry=registry,
        model_id="fake:test-model",
        workspace=tmp_path,
        control_plane=NullControlPlane(),
        config=config,
        tools=[],
    )


def test_compact_conversation_calls_mounted_compactor_and_persists(tmp_path: Path) -> None:
    agent = _agent(tmp_path, StubRegistry(), context_limits={"fake:test-model": 1_000})
    compactor = RecordingCompactor()
    agent.harness.state.compactor = compactor
    history = [Message(role="system", content="sys")] + [
        Message(role="user", content=f"message {index}") for index in range(5)
    ]

    async def _run() -> tuple[int, int]:
        await agent.persistence.save_conversation(session_id=agent.session_id, messages=history)
        result = await agent.compact_conversation()
        saved = await agent.persistence.load_conversation(session_id=agent.session_id)
        assert len(saved) == 2
        assert str(saved[1].content).startswith(COMPACTED_CONTEXT_MARK)
        return result

    assert asyncio.run(_run()) == (6, 2)
    assert len(compactor.calls) == 1
    call = compactor.calls[0]
    assert call["count"] == 6
    assert call["context_limit"] == 1_000
    assert call["tokens_used"] == estimate_prompt_tokens(history)
    assert call["context_left"] == 1_000 - call["tokens_used"]

    events = {event.event_type: event.payload for event in agent.control_plane.events}
    assert events["compaction_started"]["manual"] is True
    assert events["compaction_started"]["message_count"] == 6
    completed = events["compaction_completed"]
    assert completed["manual"] is True
    assert completed["message_count_before"] == 6
    assert completed["message_count_after"] == 2
    assert completed["estimated_tokens_before"] == estimate_prompt_tokens(history)
    assert completed["estimated_tokens_after"] > 0
    assert completed["context_limit"] == 1_000


def test_compact_conversation_uses_ai_summary_by_default(tmp_path: Path) -> None:
    registry = StubRegistry(narrative="- earlier messages numbered 1 to 7")
    agent = _agent(tmp_path, registry, compaction_keep_recent=4)
    history = [Message(role="system", content="sys")] + [
        Message(role="user", content=f"message {index}") for index in range(12)
    ]

    async def _run() -> list[Message]:
        await agent.persistence.save_conversation(session_id=agent.session_id, messages=history)
        assert await agent.compact_conversation() == (13, 7)
        return await agent.persistence.load_conversation(session_id=agent.session_id)

    saved = asyncio.run(_run())
    assert saved[1].content == "message 0"
    assert "- earlier messages numbered 1 to 7" in str(saved[2].content)
    assert [m.content for m in saved[3:]] == ["message 8", "message 9", "message 10", "message 11"]
    assert registry.calls[0]["model_id"] == "fake:test-model"


def test_compact_conversation_with_nothing_saved_returns_zero(tmp_path: Path) -> None:
    agent = _agent(tmp_path, StubRegistry())
    assert asyncio.run(agent.compact_conversation()) == (0, 0)
    assert agent.control_plane.events == []


def test_compact_conversation_without_mounted_compactor_raises(tmp_path: Path) -> None:
    agent = _agent(tmp_path, StubRegistry())
    agent.harness.state.compactor = None
    with pytest.raises(RuntimeError, match="No compactor is mounted"):
        asyncio.run(agent.compact_conversation())
