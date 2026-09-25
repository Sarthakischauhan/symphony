"""Unattended runs: no prompts, auto_decision audit trail, deny rules reach children."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core_harness import EventSink
from core_ai.content import text_from_content

from coding_agent import CodingAgent
from coding_agent.approvals import ApprovalAddon
from coding_agent.config import ApprovalConfig, CodingAgentConfig, LangfuseConfig, LearningConfig
from coding_agent.config import ensure_spawn_settings, spawn_settings_path
from scripted_registry import ScriptedRegistry, first_user_text


class NoHumanSink(EventSink):
    def __init__(self) -> None:
        super().__init__()
        self.questions: list[str] = []

    async def request_user_input(self, *, question: str, **kwargs) -> str:
        self.questions.append(question)
        raise AssertionError(f"unattended run asked a human: {question}")


def _config(**updates) -> CodingAgentConfig:
    return CodingAgentConfig(
        learning=LearningConfig(enabled=False),
        langfuse=LangfuseConfig(enabled=False),
        approvals=ApprovalConfig(deny=["rm -rf *"]),
        **updates,
    )


def _tool_results(registry: ScriptedRegistry, prompt: str) -> list[str]:
    last = [call for call in registry.calls if first_user_text(call) == prompt][-1]
    return [text_from_content(m.content) for m in last if m.role == "tool"]


def test_unattended_run_never_prompts_and_denies_in_parent_and_child(tmp_path: Path) -> None:
    (tmp_path / "keep").mkdir()
    registry = ScriptedRegistry({
        "PARENT": [[
            ("bash", {"command": "echo parent-ran"}),
            ("ask_user", {"question": "Which db?", "choices": ["sqlite", "postgres"], "default": "sqlite"}),
            ("bash", {"command": "rm -rf keep"}),
            ("spawn_agent", {"prompt": "CHILD", "label": "kid"}),
        ]],
        "CHILD": [[("bash", {"command": "rm -rf keep"})]],
    })
    sink = NoHumanSink()
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        sink=sink,
        config=_config(unattended=True),
    )
    asyncio.run(agent.run("PARENT"))

    assert sink.questions == []
    types = [event.event_type for event in sink.events]
    assert "approval_required" not in types
    assert "question_asked" not in types
    decisions = [event.payload for event in sink.events if event.event_type == "auto_decision"]
    assert any(d["kind"] == "ask_user" and d["question"] == "Which db?" for d in decisions)
    allowed = [d for d in decisions if d.get("decision") == "allow"]
    assert any(d["tool"] == "bash" and d["rule"] == "unattended" for d in allowed)
    denied = [d for d in decisions if d.get("decision") == "deny"]
    assert {d["agent_id"] for d in denied} == {agent.harness.agent_id, *agent.harness.child_tasks}
    assert all(d["rule"] == "rm -rf *" for d in denied)
    assert (tmp_path / "keep").is_dir()
    parent_results = _tool_results(registry, "PARENT")
    assert "parent-ran" in parent_results[0]
    assert parent_results[1].startswith("no human available; pick the safest reasonable option")
    assert "default: sqlite" in parent_results[1] and "choices: sqlite, postgres" in parent_results[1]
    assert "denied by rule" in parent_results[2]
    assert "denied by rule" in _tool_results(registry, "CHILD")[0]
    assert "enter_plan_mode" not in agent.harness.tools
    agent.set_mode("plan")
    assert agent.mode == "build" and not agent.plan_mode.active


def test_deny_rules_apply_even_in_always_allow_and_survive_restart(tmp_path: Path) -> None:
    ensure_spawn_settings(tmp_path, overrides={"approvals": {"mode": "always_allow", "deny": ["git push*"],
                                                             "allow": ["ls*"]}})
    reloaded = ensure_spawn_settings(tmp_path)
    assert reloaded.approvals.deny == ["git push*"] and reloaded.approvals.allow == ["ls*"]
    addon = ApprovalAddon(tmp_path, EventSink(), approvals=reloaded.approvals)

    async def gate(command: str):
        return await addon.before_tool(tool_name="bash", arguments={"command": command})

    assert "denied by rule 'git push*'" in asyncio.run(gate("git push origin main"))
    assert asyncio.run(gate("git status")) is None
    ask = reloaded.approvals.model_copy(update={"mode": "ask"})
    assert addon.policy.prompt_for(ask, "bash", {"command": "ls -la"}) == ""
    assert addon.policy.prompt_for(ask, "bash", {"command": "pwd"})
    assert addon.fork_for_child(None) is None


def test_unattended_flag_is_runtime_only(tmp_path: Path) -> None:
    config = ensure_spawn_settings(tmp_path, config=_config(unattended=True))
    assert config.unattended is True
    assert "unattended" not in spawn_settings_path(tmp_path).read_text(encoding="utf-8")
    assert ensure_spawn_settings(tmp_path).unattended is False


def test_path_deny_rules_match_the_resolved_path(tmp_path: Path) -> None:
    workspace = tmp_path / "a" / "b"
    workspace.mkdir(parents=True)
    secret = tmp_path / "etc"
    secret.mkdir()
    (workspace / "link").symlink_to(secret)
    approvals = ApprovalConfig(mode="always_allow", deny=[f"{secret}/*"], allow=["src/*"])
    addon = ApprovalAddon(workspace, EventSink(), approvals=approvals)

    def gate(tool: str, path: str):
        return asyncio.run(addon.before_tool(tool_name=tool, arguments={"path": path, "content": "x"}))

    for path in ("../../etc/passwd", f"{secret}/passwd", "link/passwd", "src/../../../etc/passwd"):
        assert "denied by rule" in gate("write_file", path), path
    assert "denied by rule" in gate("patch", "../../etc/hosts")
    assert gate("write_file", "notes/etc/passwd") is None
    ask = approvals.model_copy(update={"mode": "ask", "require_for_overwrite": True})
    (tmp_path / "a" / "outside.txt").write_text("old", encoding="utf-8")
    assert addon.policy.prompt_for(ask, "write_file", {"path": "src/../../outside.txt"})  # allow src/* not dodged
