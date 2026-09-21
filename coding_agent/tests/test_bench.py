"""Headless bench CLI, git patch, and Harbor docker argv."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from coding_agent.bench.cli import build_parser, run_bench
from coding_agent.bench.patch import git_head, workspace_diff, write_workspace_patch
from coding_agent.tui.__main__ import build_parser as tui_parser


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "bench@example.com")
    _git(workspace, "config", "user.name", "Bench")
    _git(workspace, "config", "commit.gpgsign", "false")
    (workspace / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(workspace, "add", "app.py")
    _git(workspace, "commit", "-m", "init")
    return workspace


def test_workspace_diff_includes_tracked_and_untracked(tmp_path: Path) -> None:
    workspace = _repo(tmp_path)
    start = git_head(workspace)
    (workspace / "app.py").write_text("value = 2\n", encoding="utf-8")
    (workspace / "new.py").write_text("ok = True\n", encoding="utf-8")
    (workspace / "result.json").write_text("{}\n", encoding="utf-8")
    diff = workspace_diff(workspace, start)
    assert "value = 2" in diff
    assert "new.py" in diff
    assert "result.json" not in diff
    dest = write_workspace_patch(workspace, start_ref=start)
    assert dest.name == "workspace.patch"
    assert dest.read_text(encoding="utf-8") == diff


def test_bench_parser_pins_personality_and_defaults_jev_off() -> None:
    parser = build_parser({"model": "fake:test", "max_turns": 3, "timeout_sec": 12, "personality": "precise"})
    args = parser.parse_args(["--instruction", "task.md"])
    assert args.personality == "precise"
    assert args.enable_jev is False
    assert args.max_turns == 3
    assert args.timeout == 12
    with pytest.raises(SystemExit):
        parser.parse_args(["--personality", "warm"])
    enabled = parser.parse_args(["--jev"])
    assert enabled.enable_jev is True


def test_tui_parser_is_unchanged_when_bench_is_a_subcommand() -> None:
    args = tui_parser().parse_args(["--jev"])
    assert args.enable_jev is True
    omitted = tui_parser().parse_args([])
    assert omitted.enable_jev is None


def test_run_bench_writes_patch_and_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _repo(tmp_path)
    instruction = tmp_path / "instruction.md"
    instruction.write_text("change app.py", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, *, registry, model_id, workspace, config, sink) -> None:
            del registry, model_id
            self.workspace = Path(workspace)
            captured["config"] = config
            sink.events.append(SimpleNamespace(event_type="turn_started"))
            (self.workspace / "app.py").write_text("value = 2\n", encoding="utf-8")

        async def run(self, user_input: str) -> None:
            captured["instruction"] = user_input

    monkeypatch.setattr("coding_agent.bench.cli.has_configured_provider", lambda: True)
    monkeypatch.setattr("coding_agent.bench.cli.load_provider_env", lambda _ws: None)
    monkeypatch.setattr("coding_agent.bench.cli._isolate_home", lambda: None)
    monkeypatch.setattr("coding_agent.bench.cli.CodingAgent", FakeAgent)
    monkeypatch.setattr("core_ai.build_default_registry", lambda: object())
    monkeypatch.setattr("core_ai.default_model_id", lambda _registry, model: model or "fake:test")

    args = argparse.Namespace(
        workspace=str(workspace),
        instruction=str(instruction),
        model="fake:test",
        max_turns=4,
        timeout=30.0,
        personality="precise",
        enable_jev=False,
    )
    assert run_bench(args) == 0
    result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
    assert result == {"ok": True, "turns": 1}
    patch = (workspace / "workspace.patch").read_text(encoding="utf-8")
    assert "value = 2" in patch
    assert captured["instruction"] == "change app.py"
    config = captured["config"]
    assert config.personality == "precise"
    assert config.approvals.mode == "always_allow"
    assert config.learning.enabled is False
    assert config.evaluation.enabled is False
    assert config.harness.max_turns == 4


def test_run_bench_reuses_coding_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core_ai.types import StreamEvent
    from coding_agent.agent import CodingAgent

    workspace = _repo(tmp_path)
    instruction = tmp_path / "instruction.md"
    instruction.write_text("say done", encoding="utf-8")
    seen: list[object] = []

    class Registry:
        async def stream(self, model_id, messages, tools, **kwargs):
            del model_id, messages, tools, kwargs
            yield StreamEvent(type="text_delta", delta="done")
            yield StreamEvent(type="done")

    real = CodingAgent

    def wrapping(**kwargs):
        agent = real(**kwargs)
        seen.append(agent)
        return agent

    monkeypatch.setattr("coding_agent.bench.cli.has_configured_provider", lambda: True)
    monkeypatch.setattr("coding_agent.bench.cli.load_provider_env", lambda _ws: None)
    monkeypatch.setattr("coding_agent.bench.cli._isolate_home", lambda: None)
    monkeypatch.setattr("coding_agent.bench.cli.CodingAgent", wrapping)
    monkeypatch.setattr("core_ai.build_default_registry", lambda: Registry())
    monkeypatch.setattr("core_ai.default_model_id", lambda _registry, model: model or "fake:test")

    args = argparse.Namespace(
        workspace=str(workspace),
        instruction=str(instruction),
        model="fake:test",
        max_turns=2,
        timeout=30.0,
        personality="direct",
        enable_jev=False,
    )
    assert run_bench(args) == 0
    assert len(seen) == 1
    assert isinstance(seen[0], real)
    result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["turns"] >= 1
    assert (workspace / "workspace.patch").is_file()


def test_run_bench_missing_provider_is_not_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _repo(tmp_path)
    instruction = tmp_path / "instruction.md"
    instruction.write_text("fix it", encoding="utf-8")
    monkeypatch.setattr("coding_agent.bench.cli.has_configured_provider", lambda: False)
    monkeypatch.setattr("coding_agent.bench.cli.load_provider_env", lambda _ws: None)
    args = argparse.Namespace(
        workspace=str(workspace),
        instruction=str(instruction),
        model=None,
        max_turns=1,
        timeout=5.0,
        personality="direct",
        enable_jev=False,
    )
    assert run_bench(args) == 1
    result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["turns"] == 0
    assert "error" in result
    assert (workspace / "workspace.patch").is_file()


def test_smoke_ids_are_pinned_swebench_verified() -> None:
    path = Path(__file__).resolve().parents[2] / "bench" / "smoke_ids.txt"
    ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert 5 <= len(ids) <= 10
    assert len(ids) == len(set(ids))
    for instance_id in ids:
        org, rest = instance_id.split("__", 1)
        assert org and rest.rsplit("-", 1)[-1].isdigit()


def test_harbor_docker_argv_mounts_testbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from bench.agent import docker_argv, emit_workspace_patch, symphony_model

    workspace = tmp_path / "ws"
    workspace.mkdir()
    instruction = tmp_path / "instruction.md"
    instruction.write_text("task", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    argv = docker_argv(
        workspace=workspace,
        instruction=instruction,
        model="anthropic/claude-sonnet-5",
        extra_env={"OPENAI_API_KEY": "sk-openai"},
    )
    assert argv[:3] == ["docker", "run", "--rm"]
    assert f"{workspace.resolve()}:/testbed" in argv
    assert f"{instruction.resolve()}:/instruction.md:ro" in argv
    assert "symphony-bench:latest" in argv
    assert argv[argv.index("--instruction") + 1] == "/instruction.md"
    assert "anthropic:claude-sonnet-5" in argv
    assert "--personality" in argv
    assert "--jev" not in argv
    assert "-e" in argv
    assert symphony_model("anthropic/claude-sonnet-5") == "anthropic:claude-sonnet-5"
    (workspace / "workspace.patch").write_text("diff", encoding="utf-8")
    trial_dir = tmp_path / "trial"
    emit_workspace_patch(workspace, SimpleNamespace(trial_paths=SimpleNamespace(trial_dir=trial_dir)))
    assert (trial_dir / "workspace.patch").read_text(encoding="utf-8") == "diff"
