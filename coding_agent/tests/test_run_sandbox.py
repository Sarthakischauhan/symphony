"""``symphony run|stdio --sandbox``: the policy, the re-exec, and the Seatbelt confinement (macOS)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent.protocols.stdio.server import CLIENTS
from coding_agent.run import sandbox as sandbox_module
from coding_agent.run.sandbox import sandbox_policy, wants_sandbox
from coding_agent.run.seatbelt import SandboxPolicy, SeatbeltSandbox, sandbox_available, sandbox_env


def test_osmo_is_a_stdio_client() -> None:
    assert "osmo" in CLIENTS


def test_the_policy_grants_github_only_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path / "symphony-home"))
    plain = sandbox_policy(tmp_path / "ws", github=False, home=tmp_path)
    github = sandbox_policy(tmp_path / "ws", github=True, home=tmp_path)
    assert tmp_path / "ws" in plain.writable and (tmp_path / "symphony-home").resolve() in plain.writable
    assert tmp_path / ".config" / "gh" not in plain.readable and not plain.keychain
    assert tmp_path / ".config" / "gh" in github.readable and github.keychain
    assert "com.apple.SecurityServer" in plain.profile() and "com.apple.SecurityServer" not in github.profile()


def test_the_flag_reexecs_once_without_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, list[str], dict[str, str]]] = []
    monkeypatch.setattr(sandbox_module, "sandbox_available", lambda: True)
    monkeypatch.setattr(SandboxPolicy, "wrap", lambda self, argv: ["/usr/bin/sandbox-exec", "-p", "P", *argv])
    monkeypatch.setattr(sandbox_module.os, "execve", lambda path, argv, env: seen.append((path, argv, env)) or (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.delenv("SYMPHONY_SANDBOXED", raising=False)
    argv = ["--workspace", str(tmp_path), "--sandbox-github", "--session-id", "s"]
    assert wants_sandbox(argv)
    with pytest.raises(SystemExit):
        sandbox_module.reexec_sandboxed("stdio", argv, tmp_path)
    [(path, command, env)] = seen
    assert path == "/usr/bin/sandbox-exec" and command[-6:] == ["coding_agent.cli", "stdio", "--workspace", str(tmp_path), "--session-id", "s"]
    assert env["SYMPHONY_SANDBOXED"] == "1"
    monkeypatch.setenv("SYMPHONY_SANDBOXED", "1")
    assert not wants_sandbox(argv)


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_seatbelt_keeps_writes_in_the_workspace_and_home_unread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, work = tmp_path / "home", tmp_path / "work"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("KEY")
    work.mkdir()
    monkeypatch.setenv("SYMPHONY_TEST_SECRET", "sk-live-123")
    box = SeatbeltSandbox(SandboxPolicy.confined((work,), home=home), sandbox_env(home, work))

    def run(command: str) -> str:
        return asyncio.run(box.run(command, cwd=work, timeout_s=30)).text()

    assert "[exit code 0]" in run("echo hi > made.txt")
    assert "Operation not permitted" in run(f"echo x > {home}/planted.txt")
    assert "Operation not permitted" in run(f"cat {home}/.ssh/id_ed25519")
    assert "sk-live-123" not in run("env")
    assert "Operation not permitted" in run("osascript -e 'return 1'")
