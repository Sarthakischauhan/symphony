"""``symphony doctor``: each check finds its problem, and each fix repairs it.

The shared conftest gives every test an empty HOME and SYMPHONY_HOME. The
update check never reaches PyPI here: tests run offline or stub the fetch.
"""

from __future__ import annotations

import io
import json
import os
import stat
from pathlib import Path

import pytest
from rich.console import Console

from coding_agent import doctor
from coding_agent.config import load_coding_agent_config, symphony_dir


def _ctx(tmp_path: Path, **kwargs) -> doctor.DoctorContext:
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    return doctor.DoctorContext(workspace=workspace, home=symphony_dir(), online=False, **kwargs)


def _only(findings, check: str) -> doctor.Finding:
    matches = [finding for finding in findings if finding.check == check]
    assert len(matches) == 1, findings
    return matches[0]


class _Stdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_broken_config_is_moved_aside_and_replaced_with_defaults(tmp_path: Path) -> None:
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "config.json").write_text("{ not json", encoding="utf-8")
    ctx = _ctx(tmp_path)

    finding = _only(doctor.check_config(ctx), "Config")
    assert finding.status == "fail"
    assert finding.fix is not None
    finding.fix.apply()

    assert load_coding_agent_config(path=home / "config.json").theme == "default"
    backups = list(home.glob("config.json.broken-*"))
    assert [path.read_text(encoding="utf-8") for path in backups] == ["{ not json"]
    assert _only(doctor.check_config(ctx), "Config").status == "ok"


def test_missing_plugin_theme_switches_back_to_default(tmp_path: Path) -> None:
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"theme": "gone:Nope"}), encoding="utf-8")
    ctx = _ctx(tmp_path)

    finding = _only(doctor.check_config(ctx), "Theme")
    assert finding.status == "warn" and finding.fix is not None
    finding.fix.apply()
    assert load_coding_agent_config(path=home / "config.json").theme == "default"


def test_broken_user_theme_is_moved_aside(tmp_path: Path) -> None:
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "theme.toml").write_text("[colors\n", encoding="utf-8")
    ctx = _ctx(tmp_path)

    finding = _only(doctor.check_user_theme(ctx), "Theme")
    assert finding.status == "fail" and finding.fix is not None
    finding.fix.apply()
    assert not (home / "theme.toml").exists()
    assert len(list(home.glob("theme.toml.broken-*"))) == 1
    assert list(doctor.check_user_theme(ctx)) == []


def test_secret_files_readable_by_others_are_restricted(tmp_path: Path) -> None:
    env = Path.home() / ".symphony" / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    env.chmod(0o644)

    finding = _only(doctor.check_secret_permissions(_ctx(tmp_path)), "Secrets")
    assert finding.fix is not None
    finding.fix.apply()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert list(doctor.check_secret_permissions(_ctx(tmp_path))) == []


def test_no_provider_is_a_failure_with_a_login_hint(tmp_path: Path) -> None:
    finding = _only(doctor.check_providers(_ctx(tmp_path)), "Providers")
    assert finding.status == "fail"
    assert finding.fix is None
    assert "/login" in finding.hint


def test_provider_key_in_symphony_env_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = Path.home() / ".symphony" / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    finding = _only(doctor.check_providers(_ctx(tmp_path)), "Providers")
    assert finding.status == "ok"
    assert "OpenAI" in finding.detail
    os.environ.pop("OPENAI_API_KEY", None)


def test_records_of_crashed_sessions_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = symphony_dir() / "active"
    active.mkdir(parents=True)
    record = {"session_id": "s1", "pid": 999_999, "kind": "tui", "workspace": str(tmp_path)}
    (active / "999999.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr("coding_agent.resources.usage.process_alive", lambda pid: False)

    finding = _only(doctor.check_active_sessions(_ctx(tmp_path)), "Sessions")
    assert finding.status == "warn" and finding.fix is not None
    finding.fix.apply()
    assert not (active / "999999.json").exists()


def test_unused_lock_files_are_tidied_only_once_they_pile_up(tmp_path: Path) -> None:
    active = symphony_dir() / "active"
    active.mkdir(parents=True)
    for index in range(doctor.UNUSED_LOCKS_WORTH_CLEANING - 1):
        (active / f"{index}.lock").touch()
    assert list(doctor.check_active_sessions(_ctx(tmp_path))) == []

    (active / "last.lock").touch()
    finding = _only(doctor.check_active_sessions(_ctx(tmp_path)), "Sessions")
    assert finding.status == "info" and finding.fix is not None
    finding.fix.apply()
    assert list(active.glob("*.lock")) == []


def test_update_is_offered_only_for_a_pypi_tool_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from coding_agent import updates

    monkeypatch.setattr(updates, "installed_version", lambda: "0.0.1")
    monkeypatch.setattr(updates, "pypi_tool_install", lambda: False)
    ctx = _ctx(tmp_path, fetch_latest=lambda: "0.0.9")
    ctx.online = True

    finding = _only(doctor.check_install(ctx), "Install")
    assert finding.status == "warn" and finding.fix is None
    assert "0.0.9" in finding.hint

    monkeypatch.setattr(updates, "pypi_tool_install", lambda: True)
    finding = _only(doctor.check_install(ctx), "Install")
    assert finding.fix is not None and "0.0.9" in finding.fix.summary


def test_certificate_failures_are_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ssl

    from coding_agent import updates

    def refuse() -> str:
        raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(updates, "installed_version", lambda: "0.0.1")
    ctx = _ctx(tmp_path, fetch_latest=refuse)
    ctx.online = True
    finding = _only(doctor.check_install(ctx), "Install")
    assert finding.status == "fail"
    assert "SSL_CERT_FILE" in finding.hint


def test_a_crashing_check_is_reported_and_the_rest_still_run(tmp_path: Path) -> None:
    def check_explodes(ctx):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    def check_fine(ctx):
        yield doctor.Finding("Fine", "ok", "fine")

    findings = doctor.run_checks(_ctx(tmp_path), (check_explodes, check_fine))
    assert [(item.check, item.status) for item in findings] == [("Explodes", "fail"), ("Fine", "ok")]
    assert "boom" in findings[0].detail


def _run(argv: list[str], stdin: _Stdin) -> tuple[int, str]:
    out = io.StringIO()
    code = doctor.main(argv, stdin=stdin, console=Console(file=out, width=120, color_system=None))
    return code, out.getvalue()


def test_check_mode_reports_and_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "config.json").write_text("[]", encoding="utf-8")

    code, output = _run(["--check", "--offline"], _Stdin("", tty=True))
    assert code == 1
    assert "fix: move config.json aside" in output
    assert (home / "config.json").read_text(encoding="utf-8") == "[]"


def test_answering_yes_applies_fixes_and_rechecks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "config.json").write_text("[]", encoding="utf-8")

    code, output = _run(["--offline"], _Stdin("y\n", tty=True))
    assert "Fix now?" in output
    assert "wrote defaults" in output
    assert code == 0
    load_coding_agent_config(path=home / "config.json")


def test_without_a_terminal_it_points_at_fix_instead_of_prompting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    home = symphony_dir()
    home.mkdir(parents=True)
    (home / "config.json").write_text("[]", encoding="utf-8")

    code, output = _run(["--offline"], _Stdin("", tty=False))
    assert "symphony doctor --fix" in output
    assert "Fix now?" not in output
    assert (home / "config.json").read_text(encoding="utf-8") == "[]"
    assert code == 1
