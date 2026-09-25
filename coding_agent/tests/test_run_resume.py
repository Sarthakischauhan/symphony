"""Interrupted unattended runs continue with --resume --continue; goal survives compaction."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from core_ai.content import text_from_content

from coding_agent import CodingAgent
from coding_agent.config import ensure_spawn_settings
from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.run.cli import continue_interrupted
from scripted_registry import ScriptedRegistry

GOAL = "GOAL: create done.txt"
NOTE = "previous run was interrupted at"


class Killed(BaseException):
    """Stands in for SIGKILL: no terminal checkpoint is written."""


class KillOnSecondCall(ScriptedRegistry):
    async def stream(self, model_id, messages, tools=None, **kwargs):
        if len(self.calls) == 1:
            raise Killed()
        async for event in super().stream(model_id, messages, tools, **kwargs):
            yield event


SCRIPT = {GOAL: [
    [("bash", {"command": "sleep 30", "background": True})],
    [("bash", {"command": "printf ok > done.txt"})],
]}


def _settings(workspace: Path) -> None:
    ensure_spawn_settings(workspace, overrides={
        "learning": {"enabled": False},
        "langfuse": {"enabled": False},
        "harness": {
            "context_limits": {"fake:test-model": 400},
            "context_compact_ratio": 0.05,
            "compaction_keep_recent_tools": 1,
        },
    })


def test_resume_continue_finishes_interrupted_run_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(tmp_path)
    killed = CodingAgent(
        registry=KillOnSecondCall(SCRIPT),  # type: ignore[arg-type]
        model_id="fake:test-model", workspace=tmp_path,
        config=ensure_spawn_settings(tmp_path, overrides={"unattended": True}),
    )
    with pytest.raises(Killed):
        asyncio.run(killed.run(GOAL))
    persistence = JsonlPersistence(sessions_dir(tmp_path))
    interrupted = asyncio.run(persistence.load_checkpoint(session_id=killed.session_id))
    assert interrupted.status == "running"
    assert interrupted.metadata["goal"] == GOAL
    ((lost_job, pid),) = interrupted.metadata["background_jobs"].items()
    assert isinstance(pid, int)
    # asyncio teardown reaped that job; a real SIGKILL leaves its group alive. Record a live one.
    orphan = subprocess.Popen(["sleep", "30"], start_new_session=True)
    metadata = {**interrupted.metadata, "background_jobs": {lost_job: orphan.pid}}
    asyncio.run(persistence.save_checkpoint(checkpoint=interrupted.model_copy(update={"metadata": metadata})))

    registry = ScriptedRegistry({GOAL: SCRIPT[GOAL][1:]})
    monkeypatch.setattr("core_ai.build_default_registry", lambda: registry)
    monkeypatch.setattr("core_ai.default_model_id", lambda _registry, _model: "fake:test-model")
    monkeypatch.setattr("coding_agent.run.cli.has_configured_provider", lambda: True)
    monkeypatch.setattr("coding_agent.run.cli.load_provider_env", lambda _ws: None)

    try:
        assert continue_interrupted(tmp_path) == 0
        assert orphan.wait(timeout=5) == -9  # killed before the resumed run started
    finally:
        orphan.kill()
    assert (tmp_path / "done.txt").read_text(encoding="utf-8") == "ok"
    out = capsys.readouterr().out
    assert f"continuing interrupted session {killed.session_id}" in out
    assert '"kind": "approval"' in out  # auto_decision logged, no prompt

    # The goal is in every model request of the resumed run, even after compaction.
    assert registry.calls and all(
        any(text_from_content(m.content) == GOAL for m in call) for call in registry.calls
    )
    fresh = JsonlPersistence(sessions_dir(tmp_path))
    entries = [json.loads(line) for line in fresh._path(killed.session_id).read_text().splitlines()]
    assert any(entry.get("type") == "compaction" for entry in entries)
    assert any(entry.get("event_type") == "auto_decision" for entry in entries)
    notes = [[text_from_content(m.content) for m in call if text_from_content(m.content).startswith(NOTE)]
             for call in registry.calls]
    assert len(notes[0]) == 1 and all(len(found) <= 1 for found in notes)
    assert f"background jobs {lost_job} (pid {orphan.pid}) were stopped" in notes[0][0]
    assert notes[0][0].endswith(f"continue toward the original task: {GOAL}")
    done = asyncio.run(fresh.load_checkpoint(session_id=killed.session_id))
    assert done.status == "completed" and done.metadata["goal"] == GOAL

    assert continue_interrupted(tmp_path) == 0
    assert "nothing to continue" in capsys.readouterr().out


def test_goal_survives_forced_manual_compaction(tmp_path: Path) -> None:
    _settings(tmp_path)
    agent = CodingAgent(
        registry=ScriptedRegistry({GOAL: [[("bash", {"command": f"echo step{i}"})] for i in range(4)]}),  # type: ignore[arg-type]
        model_id="fake:test-model", workspace=tmp_path,
        config=ensure_spawn_settings(tmp_path, overrides={"unattended": True, "harness": {"context_compact_ratio": None}}),
    )
    asyncio.run(agent.run(GOAL))
    before, after = asyncio.run(agent.compact_conversation())
    assert after < before
    kept = asyncio.run(agent.persistence.load_conversation(session_id=agent.session_id))
    assert [text_from_content(m.content) for m in kept if m.role == "user"][0] == GOAL
    checkpoint = asyncio.run(agent.persistence.load_checkpoint(session_id=agent.session_id))
    assert checkpoint.metadata["goal"] == GOAL


def test_resume_continue_without_sessions_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert continue_interrupted(tmp_path) == 0
    assert "nothing to continue" in capsys.readouterr().out
