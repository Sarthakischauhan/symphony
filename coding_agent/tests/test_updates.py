"""Startup update checks compare an installed release with PyPI."""

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from coding_agent.config import CodingAgentConfig, ensure_spawn_settings
from coding_agent.web.bundle import BundleError
from coding_agent.updates import (
    UpdateDecision,
    check_for_update,
    is_newer,
    startup_update_check,
)


def test_only_a_strictly_newer_release_counts() -> None:
    assert not is_newer("0.0.1", "0.0.1")
    assert not is_newer("0.0.1", "0.0.1+local")
    assert is_newer("0.0.2", "0.0.1")
    assert not is_newer("0.0.1", "0.0.2")


def test_older_client_install_is_not_updated_again() -> None:
    decision = check_for_update(current="0.0.2", latest="0.0.1", auto=True)
    assert decision.action == "continue"


def test_matching_or_unknown_versions_continue() -> None:
    assert check_for_update(current="0.0.1", latest="0.0.1", auto=True).action == "continue"
    assert check_for_update(current=None, latest="0.0.2", auto=True).action == "continue"
    assert check_for_update(current="0.0.1", latest=None, auto=False).action == "continue"
    assert check_for_update(current="0.0.1", latest="0.0.2", auto=False, enabled=False).action == "continue"


def test_auto_updates_and_manual_mode_asks() -> None:
    auto = check_for_update(current="0.0.1", latest="0.0.2", auto=True)
    manual = check_for_update(current="0.0.1", latest="0.0.2", auto=False)
    assert auto.action == "update"
    assert manual.action == "ask"
    assert "0.0.2" in manual.message


def test_prompt_no_keeps_installed_version(monkeypatch) -> None:
    messages: list[str] = []
    decision = startup_update_check(
        {"updates": {"enabled": True, "auto": False}},
        current=lambda: "0.0.1",
        latest=lambda: "0.0.2",
        prompt=lambda _current, _latest: False,
        install=lambda _target: pytest.fail("declined update must not install"),
        output=messages.append,
        enabled=True,
    )
    assert decision == UpdateDecision("continue", "0.0.1", "0.0.2")
    assert messages == ["Continuing with symphony-code 0.0.1."]


def test_prompt_yes_installs_exact_release() -> None:
    installed: list[str] = []

    def install(target: str) -> CompletedProcess[str]:
        installed.append(target)
        return CompletedProcess([], 0, "", "")

    def install_web(target: str, root: Path) -> Path:
        installed.append(f"web {target} {root.name}")
        return root

    decision = startup_update_check(
        {"updates": {"auto": False}},
        current=lambda: "0.0.1",
        latest=lambda: "0.0.2",
        prompt=lambda _current, _latest: True,
        install=install,
        output=lambda _message: None,
        enabled=True,
        install_web=install_web,
        web_root=lambda: Path("web"),
    )
    assert installed == ["0.0.2", "web 0.0.2 web"]
    assert decision.action == "updated"


def test_auto_install_failure_keeps_current_version() -> None:
    messages: list[str] = []
    decision = startup_update_check(
        {"updates": {"auto": True}},
        current=lambda: "0.0.1",
        latest=lambda: "0.0.2",
        install=lambda _target: CompletedProcess([], 1, "", "network down"),
        output=messages.append,
        enabled=True,
    )
    assert decision.action == "failed"
    assert any("network down" in message for message in messages)


def test_config_defaults_ask_before_updating(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path))
    config = ensure_spawn_settings(tmp_path)
    assert config.updates.enabled is True
    assert config.updates.auto is False
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["updates"] == {"enabled": True, "auto": False}
    CodingAgentConfig.model_validate({"updates": {"auto": True}})
    with pytest.raises(ValueError):
        CodingAgentConfig.model_validate({"updates": {"channel": "beta"}})


def test_failed_web_bundle_still_reports_the_package_update() -> None:
    messages: list[str] = []

    def broken(target: str, root: Path) -> Path:
        raise BundleError("checksum mismatch")

    decision = startup_update_check(
        {"updates": {"auto": True}},
        current=lambda: "0.0.1",
        latest=lambda: "0.0.2",
        install=lambda _target: CompletedProcess([], 0, "", ""),
        output=messages.append,
        enabled=True,
        install_web=broken,
        web_root=lambda: Path("web"),
    )
    assert decision.action == "updated"
    assert any("checksum mismatch" in m and "symphony web --update" in m for m in messages)
