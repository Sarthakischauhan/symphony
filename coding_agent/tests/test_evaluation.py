"""Tests for optional Jev critic mode (findings + optional message)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from core_ai.types import Message, StreamEvent
from core_harness import EventSink, Tool
from core_harness.addons.addon import Addon
from core_harness.models import HarnessResult, UsageTotals

from coding_agent import CodingAgent
from coding_agent.config import (
    CodingAgentConfig,
    EvaluationConfig,
    LangfuseConfig,
    LearningConfig,
    ensure_spawn_settings,
)
from coding_agent.evaluation import (
    CONTINUE_NORMALLY,
    FINISH_QUESTIONS,
    JEV_SYSTEM_SEGMENT,
    JevAddon,
    MockEvaluator,
    NUDGE_MARKER,
    START_QUESTIONS,
    StubEvaluator,
    VercelJevEvaluator,
    PolicyDecision,
    apply_findings_gate,
    build_run_state,
    clip_text,
    critic_message,
    decide_next_step,
    format_nudge,
    jev_from_config,
    should_nudge,
)
from coding_agent.evaluation.protocol import EvaluationFinding, EvaluationResult
from coding_agent.plan import PlanStore
from coding_agent.tui.__main__ import build_parser
from coding_agent.tui.commands.catalog import SLASH_COMMANDS
from coding_agent.tui.commands.manager import jev_enabled_from_argument


class QuietRegistry:
    async def stream(self, model_id, messages, tools=None, **kwargs):
        del model_id, messages, tools, kwargs
        yield StreamEvent(type="text_delta", delta="done")
        yield StreamEvent(type="done")


class ToolThenDoneRegistry:
    def __init__(self) -> None:
        self.turns = 0

    async def stream(self, model_id, messages, tools=None, **kwargs):
        del model_id, messages, tools, kwargs
        self.turns += 1
        if self.turns == 1:
            yield StreamEvent(type="toolcall_start", tool_call_id="c1", tool_name="echo")
            yield StreamEvent(type="toolcall_delta", delta='{"text":"hello"}')
            yield StreamEvent(type="done")
            return
        yield StreamEvent(type="text_delta", delta="finished")
        yield StreamEvent(type="done")


def _config(*, enabled: bool) -> CodingAgentConfig:
    return CodingAgentConfig(
        learning=LearningConfig(enabled=False),
        langfuse=LangfuseConfig(enabled=False),
        evaluation=EvaluationConfig(enabled=enabled),
    )


def _agent(tmp_path: Path, *, enabled: bool, registry: Any = None, tools: list | None = None) -> CodingAgent:
    return CodingAgent(
        registry=registry or QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[] if tools is None else tools,
        config=_config(enabled=enabled),
        sink=EventSink(),
    )


def _jev(agent: CodingAgent) -> JevAddon:
    addon = next(item for item in agent.harness.addons if item.name == "jev")
    assert isinstance(addon, JevAddon)
    return addon


def test_disabled_does_not_mount_addon(tmp_path: Path) -> None:
    agent = _agent(tmp_path, enabled=False)
    assert not any(addon.name == "jev" for addon in agent.harness.addons)


def test_disabled_run_makes_zero_eval_calls(tmp_path: Path) -> None:
    agent = _agent(tmp_path, enabled=False)
    assert jev_from_config(EvaluationConfig(enabled=False)) is None
    asyncio.run(agent.run("do a thing"))
    assert not any(addon.name == "jev" for addon in agent.harness.addons)


def test_enabled_calls_on_start_and_on_finish_once(tmp_path: Path) -> None:
    agent = _agent(tmp_path, enabled=True)
    mock = MockEvaluator()
    _jev(agent).evaluator = mock
    asyncio.run(agent.run("implement the feature"))
    assert len(mock.starts) == 1
    assert len(mock.finishes) == 1
    assert mock.starts[0].phase == "start"
    assert mock.finishes[0].phase == "finish"
    assert mock.starts[0].request == "implement the feature"
    assert "implement the feature" in mock.finishes[0].request or mock.finishes[0].request == "implement the feature"


def test_enabled_multi_turn_still_two_eval_calls(tmp_path: Path) -> None:
    def echo(text: str = "") -> str:
        return text

    registry = ToolThenDoneRegistry()
    agent = _agent(
        tmp_path,
        enabled=True,
        registry=registry,
        tools=[Tool(echo, name="echo", description="Echo text")],
    )
    mock = MockEvaluator()
    _jev(agent).evaluator = mock
    asyncio.run(agent.run("call echo then finish"))
    assert registry.turns == 2
    assert len(mock.starts) == 1
    assert len(mock.finishes) == 1


def test_evaluator_not_invoked_from_before_turn_or_on_tool(tmp_path: Path) -> None:
    mock = MockEvaluator()
    addon = JevAddon(EvaluationConfig(enabled=True), evaluator=mock)
    assert JevAddon.before_turn is Addon.before_turn
    assert JevAddon.on_tool is Addon.on_tool
    assert JevAddon.before_tool is Addon.before_tool
    assert JevAddon.after_turn is Addon.after_turn

    async def scenario() -> None:
        await addon.before_turn(turn=0, messages=[])
        await addon.on_tool(tool_call=None, result=None)
        await addon.before_tool(tool_name="bash", arguments={})
        await addon.after_turn(turn=0, messages=[])

    asyncio.run(scenario())
    assert mock.starts == []
    assert mock.finishes == []


def test_state_budget_clips_fields() -> None:
    config = EvaluationConfig(
        enabled=True,
        brief_max_chars=8,
        plan_max_chars=10,
        final_max_chars=12,
        request_max_chars=16,
        observations_max_chars=20,
        last_tool_results_max_chars=18,
        files_modified_max=2,
    )
    huge = "x" * 5000
    messages = [
        Message(role="user", content=huge),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "w1",
                    "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py"})},
                },
                {
                    "id": "w2",
                    "function": {"name": "write_file", "arguments": json.dumps({"path": "b.py"})},
                },
                {
                    "id": "w3",
                    "function": {"name": "write_file", "arguments": json.dumps({"path": "c.py"})},
                },
            ],
        ),
        Message(role="tool", tool_call_id="w1", content=huge),
    ]
    plan = "# Plan\n\n- [ ] first\n- [x] second\n" + huge
    state = build_run_state(
        config=config,
        phase="finish",
        request=huge,
        messages=messages,
        plan_text=plan,
        final=huge,
    )
    assert len(state.request) <= 16
    assert len(state.brief) <= 8
    assert len(state.plan) <= 10
    assert len(state.final) <= 12
    assert huge not in json.dumps(state.as_eval_state())
    assert len(state.files_modified) == 2
    assert sum(len(item) for item in state.last_tool_results) <= 18
    assert sum(len(item) for item in state.observations) <= 20
    assert clip_text(huge, 4) == "xxx…"


def test_eval_state_redacts_secrets_from_tool_plan_and_final() -> None:
    assigned = "OPENAI_API_KEY=sk-leakedkey99999"
    token = "sk-secretABCDEFG12"
    messages = [
        Message(role="user", content=f"Fix the leak {assigned}"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": f"echo {assigned}"}),
                    },
                }
            ],
        ),
        Message(role="tool", tool_call_id="c1", content=f"printed {token} and {assigned}"),
    ]
    state = build_run_state(
        config=EvaluationConfig(enabled=True),
        phase="finish",
        request=f"rotate {assigned}",
        messages=messages,
        plan_text=f"- [ ] keep {token} out of the plan\n- [x] done",
        final=f"shipped with {token}",
    )
    payload = json.dumps(state.as_eval_state())
    assert assigned not in payload
    assert token not in payload
    assert "sk-leakedkey99999" not in payload
    assert "sk-secretABCDEFG12" not in payload
    assert "[REDACTED]" in payload
    assert assigned not in state.request
    assert assigned not in state.brief
    assert token not in state.plan
    assert token not in state.final
    assert all(token not in item and assigned not in item for item in state.last_tool_results)
    assert all(assigned not in item for item in state.observations)


def test_vercel_eval_payload_redacts_secrets_end_to_end() -> None:
    assigned = "OPENAI_API_KEY=sk-leakedkey99999"
    token = "sk-secretABCDEFG12"
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": {"task_complete": {"type": "boolean", "value": True}}})

    evaluator = VercelJevEvaluator(
        EvaluationConfig(enabled=True),
        api_key="gw-key",
        transport=httpx.MockTransport(handler),
    )
    state = build_run_state(
        config=EvaluationConfig(),
        phase="finish",
        request=f"fix {assigned}",
        messages=[
            Message(role="tool", tool_call_id="c1", content=f"stdout {token} {assigned}"),
        ],
        plan_text=f"Do not paste {token}",
        final=f"done {assigned}",
    )
    asyncio.run(evaluator.on_finish(state))
    blob = json.dumps(captured["payload"])
    assert assigned not in blob
    assert token not in blob
    assert "sk-leakedkey99999" not in blob
    assert "sk-secretABCDEFG12" not in blob
    assert captured["payload"]["state"]["final"].startswith("done OPENAI_API_KEY")
    assert "[REDACTED]" in captured["payload"]["state"]["final"]
    assert "[REDACTED]" in captured["payload"]["state"]["last_tool_results"][0]
    assert "[REDACTED]" in captured["payload"]["state"]["plan"]


def test_fail_open_on_evaluator_error(tmp_path: Path) -> None:
    mock = MockEvaluator(error=RuntimeError("gateway down"))
    store = PlanStore(tmp_path)
    original = store.begin("task").read_text(encoding="utf-8")
    addon = JevAddon(
        EvaluationConfig(enabled=True),
        evaluator=mock,
        plan_store=store,
    )

    async def scenario() -> None:
        await addon.before_run(messages=[Message(role="user", content="task")])
        await addon.after_run(
            task="task",
            result=HarnessResult(
                output_text="ok",
                messages=[],
                tool_calls=[],
                usage=UsageTotals(),
            ),
            messages=[],
        )

    asyncio.run(scenario())
    assert addon.last_start is not None
    assert addon.last_finish is not None
    assert addon.last_start.status == "error"
    assert addon.last_finish.status == "error"
    assert addon.gated_action == CONTINUE_NORMALLY
    assert store.path.read_text(encoding="utf-8") == original


def test_findings_do_not_rewrite_plan(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    path = store.begin("ship it")
    original = path.read_text(encoding="utf-8")
    mock = MockEvaluator(
        finish=EvaluationResult(
            phase="finish",
            findings=[
                EvaluationFinding(question="remaining_work", kind="boolean", value=True, label="true"),
                EvaluationFinding(question="next_action", kind="choice", value="retry", label="retry"),
            ],
        )
    )
    addon = JevAddon(EvaluationConfig(enabled=True), evaluator=mock, plan_store=store)
    asyncio.run(
        addon.after_run(
            task="ship it",
            result=HarnessResult(output_text="done", messages=[], tool_calls=[], usage=UsageTotals()),
            messages=[],
        )
    )
    assert path.read_text(encoding="utf-8") == original
    assert apply_findings_gate(addon.last_finish) == "retry"
    assert addon.gated_action == "retry"
    assert addon.plan_mode is None or not addon.plan_mode.active
    assert addon.consume_follow_up() is None


def test_policy_maps_start_replan_and_finish_retry() -> None:
    replan = EvaluationResult(
        phase="start",
        findings=[
            EvaluationFinding(
                question="needs_replan",
                kind="boolean",
                value=True,
                probs={"true": 0.91, "false": 0.09},
                rationale="plan is stale",
            ),
        ],
    )
    decision = decide_next_step(replan)
    assert decision.action == "replan"
    assert "Revise the plan" in critic_message(decision)

    retry = EvaluationResult(
        phase="finish",
        findings=[
            EvaluationFinding(question="next_action", kind="choice", value="retry", label="retry"),
        ],
    )
    assert decide_next_step(retry).action == "retry"
    skipped = EvaluationResult(phase="start", status="error")
    assert decide_next_step(skipped).action == CONTINUE_NORMALLY


def test_bare_label_does_not_clear_actuation_threshold() -> None:
    bare = EvaluationResult(
        phase="start",
        findings=[
            EvaluationFinding(
                question="needs_replan",
                kind="boolean",
                value=True,
                label="true",
                rationale="plan looks stale",
            ),
        ],
    )
    assert decide_next_step(bare).action == CONTINUE_NORMALLY
    assert should_nudge(bare) is True

    label_only = EvaluationResult(
        phase="finish",
        findings=[
            EvaluationFinding(
                question="unsupported_claims",
                kind="boolean",
                label="true",
            ),
        ],
    )
    assert decide_next_step(label_only).action == CONTINUE_NORMALLY
    assert should_nudge(label_only) is True

    confident = EvaluationResult(
        phase="start",
        findings=[
            EvaluationFinding(
                question="needs_replan",
                kind="boolean",
                value=True,
                label="true",
                probs={"true": 0.88, "false": 0.12},
            ),
        ],
    )
    assert decide_next_step(confident).action == "replan"


def test_start_replan_is_injected_for_the_model(tmp_path: Path) -> None:
    mock = MockEvaluator(
        start=EvaluationResult(
            phase="start",
            findings=[
                EvaluationFinding(
                    question="needs_replan",
                    kind="boolean",
                    value=True,
                    rationale="current plan cannot ship the request",
                )
            ],
        )
    )
    agent = _agent(tmp_path, enabled=True)
    addon = _jev(agent)
    addon.evaluator = mock
    messages: list[Message] = [Message(role="user", content="implement the feature")]
    asyncio.run(addon.before_run(task="implement the feature", messages=messages))
    assert addon.gated_action == CONTINUE_NORMALLY
    assert addon.plan_mode is None or not addon.plan_mode.active
    assert messages[-1].role == "user"
    assert NUDGE_MARKER in str(messages[-1].content)
    assert "Plan mode was not opened." in str(messages[-1].content)
    assert addon.consume_follow_up() is None
    assert sum(1 for item in messages if NUDGE_MARKER in str(item.content)) == 1


def test_conflicting_bools_inject_one_message_no_second_run(tmp_path: Path) -> None:
    class CountingRegistry:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            self.calls += 1
            yield StreamEvent(type="text_delta", delta="done")
            yield StreamEvent(type="done")

    registry = CountingRegistry()
    agent = _agent(tmp_path, enabled=True, registry=registry)
    mock = MockEvaluator(
        finish=EvaluationResult(
            phase="finish",
            findings=[
                EvaluationFinding(
                    question="task_complete",
                    kind="boolean",
                    value=True,
                    label="true",
                ),
                EvaluationFinding(
                    question="remaining_work",
                    kind="boolean",
                    value=True,
                    label="true",
                    rationale="tests still fail",
                ),
            ],
        )
    )
    addon = _jev(agent)
    addon.evaluator = mock
    result = asyncio.run(agent.run("ship it"))
    notes = [
        item
        for item in result.messages
        if item.role == "user" and NUDGE_MARKER in str(item.content)
    ]
    assert len(notes) == 1
    assert "task_complete" in str(notes[0].content)
    assert "remaining_work" in str(notes[0].content)
    assert "Plan mode was not opened." in str(notes[0].content)
    assert agent.plan_mode.active is False
    assert agent.mode != "plan"
    assert registry.calls == 1
    assert addon.follow_ups == 0
    assert addon.gated_action == "review"
    assert addon.consume_follow_up() is None
    assert CodingAgentConfig().evaluation.honour_follow_up is False


def test_finish_policy_conflict_finish_only_and_remaining_only() -> None:
    both = EvaluationResult(
        phase="finish",
        findings=[
            EvaluationFinding(
                question="task_complete",
                kind="boolean",
                value=True,
                label="true",
            ),
            EvaluationFinding(
                question="remaining_work",
                kind="boolean",
                value=True,
                label="true",
                rationale="tests still fail",
            ),
        ],
    )
    conflict = decide_next_step(both)
    assert conflict.action == "review"
    assert should_nudge(both) is True
    note = format_nudge(both)
    assert "task_complete" in note
    assert "remaining_work" in note

    finish_only = EvaluationResult(
        phase="finish",
        findings=[
            EvaluationFinding(
                question="next_action",
                kind="choice",
                value="finish",
                label="finish",
            ),
            EvaluationFinding(
                question="task_complete",
                kind="boolean",
                value=True,
                label="true",
                probs={"true": 0.95, "false": 0.05},
            ),
        ],
    )
    assert decide_next_step(finish_only).action == CONTINUE_NORMALLY
    assert should_nudge(finish_only) is False

    remaining_only = EvaluationResult(
        phase="finish",
        findings=[
            EvaluationFinding(
                question="remaining_work",
                kind="boolean",
                value=True,
                label="true",
                rationale="still shipping",
                probs={"true": 0.94, "false": 0.06},
            ),
        ],
    )
    assert decide_next_step(remaining_only).action == CONTINUE_NORMALLY
    assert should_nudge(remaining_only) is True
    assert "remaining_work" in format_nudge(remaining_only)


def test_honour_follow_up_stays_off_by_default() -> None:
    mock = MockEvaluator(
        finish=EvaluationResult(
            phase="finish",
            findings=[
                EvaluationFinding(
                    question="next_action",
                    kind="choice",
                    value="retry",
                    label="retry",
                ),
            ],
        )
    )
    addon = JevAddon(EvaluationConfig(enabled=True), evaluator=mock)
    asyncio.run(
        addon.after_run(
            task="ship it",
            result=HarnessResult(
                output_text="done",
                messages=[],
                tool_calls=[],
                usage=UsageTotals(),
            ),
            messages=[],
        )
    )
    assert addon.gated_action == "retry"
    assert addon.config.honour_follow_up is False
    assert addon.consume_follow_up() is None
    assert addon.follow_ups == 0


def test_nudge_replaces_prior_marker_instead_of_stacking() -> None:
    mock = MockEvaluator(
        start=EvaluationResult(
            phase="start",
            findings=[
                EvaluationFinding(
                    question="needs_replan",
                    kind="boolean",
                    value=True,
                    label="true",
                )
            ],
        )
    )
    addon = JevAddon(EvaluationConfig(enabled=True), evaluator=mock)
    messages = [
        Message(role="user", content="task"),
        Message(role="user", content=f"{NUDGE_MARKER} leftover from last phase."),
    ]
    asyncio.run(addon.before_run(task="task", messages=messages))
    notes = [item for item in messages if NUDGE_MARKER in str(item.content)]
    assert len(notes) == 1
    assert "needs_replan" in str(notes[0].content)
    assert "leftover from last phase" not in str(notes[0].content)


def test_format_nudge_is_a_template_not_an_llm_call() -> None:
    findings = [
        EvaluationFinding(
            question="unsupported_claims",
            kind="boolean",
            value=True,
            label="true",
            rationale="claimed tests passed",
        ),
        EvaluationFinding(
            question="next_action",
            kind="choice",
            value="review",
            label="review",
        ),
    ]
    note = format_nudge(findings)
    assert note.startswith(NUDGE_MARKER)
    assert "unsupported_claims" in note
    assert "Suggested next_action: review." in note
    assert "Plan mode was not opened." in note
    assert should_nudge(findings) is True


def test_nudge_and_critic_run_rationale_through_bound_text() -> None:
    leaked = "OPENAI_API_KEY=sk-leakedkey99999 " + ("x" * 400)
    finding = EvaluationFinding(
        question="unsupported_claims",
        kind="boolean",
        value=True,
        label="true",
        rationale=leaked,
    )
    note = format_nudge(
        [
            finding,
            EvaluationFinding(
                question="next_action",
                kind="choice",
                value="review",
                label="review",
            ),
        ]
    )
    assert "sk-leakedkey99999" not in note
    assert "…" in note
    message = critic_message(
        PolicyDecision(action="review", reason="review", finding=finding)
    )
    assert "sk-leakedkey99999" not in message
    assert "…" in message


def test_jev_mode_segment_precedes_personality_when_enabled(tmp_path: Path) -> None:
    from coding_agent.personalities import PERSONALITY_HEADING

    enabled = _agent(tmp_path, enabled=True)
    prompt = enabled.harness.system_prompt
    assert JEV_SYSTEM_SEGMENT in prompt
    assert NUDGE_MARKER in prompt
    assert PERSONALITY_HEADING in prompt
    assert prompt.index("# Jev mode") < prompt.index(PERSONALITY_HEADING)
    disabled = _agent(tmp_path, enabled=False)
    assert JEV_SYSTEM_SEGMENT not in disabled.harness.system_prompt


def test_jev_flag_parses_into_evaluation_config(tmp_path: Path) -> None:
    parser = build_parser()
    enabled = parser.parse_args(["--jev"])
    assert enabled.enable_jev is True
    omitted = parser.parse_args([])
    assert omitted.enable_jev is None
    config = ensure_spawn_settings(
        tmp_path,
        overrides={"evaluation": {"enabled": bool(enabled.enable_jev)}},
    )
    assert config.evaluation.enabled is True
    assert config.evaluation.provider == "vercel"
    assert config.evaluation.model == "typesafe-ai/jev"
    assert config.evaluation.on_error == "fail-open"
    assert config.evaluation.honour_follow_up is False
    assert CodingAgentConfig().evaluation.enabled is False
    assert CodingAgentConfig().evaluation.honour_follow_up is False


def test_slash_jev_is_mode_toggle_not_model_switch() -> None:
    names = [command.name for command in SLASH_COMMANDS]
    assert "jev" in names
    assert jev_enabled_from_argument(False, "") is True
    assert jev_enabled_from_argument(True, "off") is False
    assert jev_enabled_from_argument(False, "on") is True
    assert jev_enabled_from_argument(True, "model") is None


def test_child_does_not_inherit_jev(tmp_path: Path) -> None:
    agent = CodingAgent(
        registry=QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=_config(enabled=True),
    )
    assert any(addon.name == "jev" for addon in agent.harness.addons)
    child_addons = agent._spawn_child_config(prompt="x").addon_factory(agent.harness)
    assert not any(addon.name == "jev" for addon in child_addons)


def test_core_harness_has_no_jev_or_typesafe_imports() -> None:
    import core_harness

    root = Path(core_harness.__file__).resolve().parent
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        if "jev" in text or "typesafe" in text:
            offenders.append(str(path))
    assert offenders == []


def test_vercel_jev_evaluator_wires_v1_questions() -> None:
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "plan_sufficient": {"type": "boolean", "probability": 0.8},
                    "next_action": {"type": "choice", "choice": "continue"},
                }
            },
        )

    evaluator = VercelJevEvaluator(
        EvaluationConfig(enabled=True),
        api_key="gw-key",
        transport=httpx.MockTransport(handler),
    )
    state = build_run_state(
        config=EvaluationConfig(),
        phase="start",
        request="fix tests",
        plan_text="- [ ] write tests",
    )
    result = asyncio.run(evaluator.on_start(state))
    payload = captured["payload"]
    assert captured["url"].endswith("/v4/ai/evaluation-model")
    assert payload["questions"] == START_QUESTIONS
    assert payload["state"]["request"] == "fix tests"
    assert "messages" not in payload["state"]
    assert result.status == "ok"
    assert result.decisions[0].kind == "boolean"
    assert result.decisions[0].probs is not None


def test_vercel_jev_evaluator_finish_questions_and_fail_open() -> None:
    async def ok_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["questions"] == FINISH_QUESTIONS
        return httpx.Response(
            200,
            json={"answers": {"task_complete": {"type": "boolean", "value": True}}},
        )

    evaluator = VercelJevEvaluator(
        EvaluationConfig(enabled=True),
        api_key="gw-key",
        transport=httpx.MockTransport(ok_handler),
    )
    state = build_run_state(config=EvaluationConfig(), phase="finish", final="all good")
    result = asyncio.run(evaluator.on_finish(state))
    assert result.status == "ok"
    assert result.decisions[0].name == "task_complete"

    async def boom(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, text="nope")

    failing = VercelJevEvaluator(
        EvaluationConfig(enabled=True),
        api_key="gw-key",
        transport=httpx.MockTransport(boom),
    )
    failed = asyncio.run(failing.on_finish(state))
    assert failed.status == "error"
    skipped = asyncio.run(
        VercelJevEvaluator(EvaluationConfig(enabled=True), api_key="").on_start(state)
    )
    assert skipped.status == "skipped"


def test_stub_evaluator_skips() -> None:
    stub = StubEvaluator()
    state = build_run_state(config=EvaluationConfig(), phase="start")
    assert asyncio.run(stub.on_start(state)).status == "skipped"
    assert asyncio.run(stub.on_finish(state)).status == "skipped"
