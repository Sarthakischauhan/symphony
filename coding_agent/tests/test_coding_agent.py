import asyncio
from pathlib import Path

from core_ai.types import Message, StreamEvent
from core_harness import EventSink
from coding_agent import CodingAgent
from coding_agent.compaction import InferenceCompactor
from coding_agent.compaction.prompts import COMPACTION_SYSTEM_PROMPT
from coding_agent.config import CodingAgentConfig, LearningConfig, spawn_settings_path
from coding_agent.persistence import JsonlPersistence


def test_coding_agent_defaults_are_safer_and_learning_is_enabled(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[],
    )
    assert agent.learning_loop is not None
    assert any(addon.name == "learning" for addon in agent.harness.addons)
    defaults = CodingAgentConfig().harness
    assert agent.harness.max_turns == defaults.max_turns == 24
    assert agent.harness.limits.max_tool_calls == defaults.max_tool_calls
    assert agent.harness.limits.max_tokens == defaults.max_tokens
    assert agent.harness.limits.max_runtime_seconds == 600.0
    settings_path = spawn_settings_path(tmp_path)
    assert settings_path.exists()
    saved = CodingAgentConfig.model_validate_json(settings_path.read_text(encoding="utf-8"))
    assert saved.harness.max_turns == 24
    assert saved.harness.tool_result_prune_tokens == 48_000
    assert saved.harness.context_compact_threshold == 16_000
    assert saved.harness.compaction_keep_recent == 10
    assert isinstance(agent.harness.state.compactor, InferenceCompactor)
    assert isinstance(agent.persistence, JsonlPersistence)
    assert agent.harness.persistence is agent.persistence


def test_coding_agent_registers_spawn_agent_on_default_tools(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    assert "spawn_agent" in agent.harness.tools
    assert "read_file" in agent.harness.tools
    assert any(addon.name == "subagent" for addon in agent.harness.addons)


def test_coding_agent_child_runs_without_approvals(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualEventSink

    plane = TextualEventSink(workspace=tmp_path)
    plane.set_approval_mode("ask")
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        sink=plane,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    cfg = agent._spawn_child_config(
        prompt="x",
        max_turns=99,
        model_id=" fake:child ",
    )
    assert cfg.model_id == "fake:child"
    assert cfg.max_turns == agent.harness.config.spawn_max_turns
    assert cfg.sink is plane
    assert plane.approvals.mode == "ask"
    assert any(addon.name == "approval" for addon in agent.harness.addons)
    child_addons = cfg.addon_factory(agent.harness)
    assert not any(addon.name == "approval" for addon in child_addons)


def test_coding_agent_child_stays_autonomous_if_parent_already_allows(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualEventSink

    plane = TextualEventSink(workspace=tmp_path)
    plane.set_approval_mode("always_allow")
    agent = CodingAgent(
        registry=CapturingRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        sink=plane,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    cfg = agent._spawn_child_config()
    assert cfg.sink is plane
    assert plane.approvals.mode == "always_allow"
    child_addons = cfg.addon_factory(agent.harness)
    assert not any(addon.name == "approval" for addon in child_addons)


class CapturingRegistry:
    """Records turn calls; answers compaction summary calls with a fixed narrative."""

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.summary_calls: list[list[Message]] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        tools: list[dict],
        **kwargs: object,
    ):
        if messages and messages[0].content == COMPACTION_SYSTEM_PROMPT:
            self.summary_calls.append(list(messages))
            yield StreamEvent(type="text_delta", delta="- earlier asks handled")
            yield StreamEvent(type="done")
            return
        self.calls.append(list(messages))
        yield StreamEvent(type="text_delta", delta="done")
        yield StreamEvent(
            type="usage",
            prompt_tokens=10,
            completion_tokens=1,
            total_tokens=11,
        )
        yield StreamEvent(type="done")


def test_coding_agent_compacts_oversized_persisted_context(tmp_path: Path) -> None:
    registry = CapturingRegistry()
    sink = EventSink()
    config = CodingAgentConfig()
    config = config.model_copy(
        update={
            "learning": config.learning.model_copy(update={"enabled": False}),
            "harness": config.harness.model_copy(
                update={
                    "context_limits": {"fake:test-model": 100},
                    "context_warn_threshold": 30,
                    "context_compact_threshold": 20,
                    "compaction_keep_recent": 2,
                }
            ),
        }
    )
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        sink=sink,
        config=config,
        tools=[],
    )

    async def _run() -> None:
        history = [
            Message(role="user", content=f"old message {index} " * 20)
            for index in range(6)
        ]
        await agent.persistence.save_conversation(
            session_id=agent.session_id,
            messages=history,
        )

        result = await agent.run("new request")

        sent = registry.calls[0]
        assert sent[0].role == "system"
        assert sent[1].content == history[0].content
        assert str(sent[2].content).startswith("[compacted earlier context]")
        assert "- earlier asks handled" in str(sent[2].content)
        assert len(registry.summary_calls) == 1
        assert sent[-2].content == history[-1].content
        assert sent[-1].content == "new request"
        assert len(result.messages) == len(sent) + 1
        saved = await agent.persistence.load_conversation(session_id=agent.session_id)
        assert saved == result.messages

    asyncio.run(_run())

    event_types = [event.event_type for event in sink.events]
    assert event_types.index("compaction_started") < event_types.index("turn_started")
    assert "compaction_completed" in event_types
