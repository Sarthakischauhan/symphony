"""``symphony run --unattended --detach`` returns at once and the child keeps writing its session."""

from __future__ import annotations

import json
import os
import signal
import textwrap
import time
from pathlib import Path

import pytest

from coding_agent.persistence import sessions_dir
from coding_agent.run.cli import build_parser, main

# Loaded by the detached child through PYTHONPATH: swaps in a slow scripted provider.
FAKE_PROVIDER = textwrap.dedent("""
    import core_ai
    from scripted_registry import ScriptedRegistry

    script = [[("bash", {"command": f"echo tick{i}"})] for i in range(6)]
    core_ai.build_default_registry = lambda: ScriptedRegistry({"slow task": script}, delay=0.4)
    core_ai.default_model_id = lambda registry, model: "fake:test-model"
    core_ai.has_configured_provider = lambda: True
""")


def _wait_for(predicate, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_run_requires_unattended_acknowledgement() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["do it"])
    args = build_parser().parse_args(["--unattended", "--detach", "--model", "m", "do it"])
    assert args.detach and args.task == "do it" and args.model == "m"


def test_detach_returns_fast_and_child_keeps_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(FAKE_PROVIDER, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(hook), str(Path(__file__).parent)]))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (Path(os.environ["HOME"]) / ".symphony").mkdir(exist_ok=True)
    (Path(os.environ["HOME"]) / ".symphony" / "config.json").write_text(
        json.dumps({"learning": {"enabled": False}, "langfuse": {"enabled": False}}), encoding="utf-8"
    )

    started = time.monotonic()
    assert main(["--unattended", "--detach", "--workspace", str(workspace), "slow task"]) == 0
    assert time.monotonic() - started < 1.0

    out = capsys.readouterr().out
    session_id = out.split("session ")[1].split()[0]
    info = json.loads((sessions_dir() / f"{session_id}.run.json").read_text(encoding="utf-8"))
    pid = info["pid"]
    try:
        assert f"pid {pid}" in out and info["session_id"] == session_id
        assert "--detach" not in info["argv"] and info["argv"][-2:] == ["--session-id", session_id]
        os.kill(pid, 0)  # alive
        session = sessions_dir() / f"{session_id}.jsonl"
        assert _wait_for(session.exists), Path(info["log"]).read_text(encoding="utf-8")
        size = session.stat().st_size
        assert _wait_for(lambda: session.stat().st_size > size), Path(info["log"]).read_text(encoding="utf-8")
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
