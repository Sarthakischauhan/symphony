"""Startup update checks compare an installed release with PyPI."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from importlib.metadata import Distribution

from coding_agent import updates
from coding_agent.config import CodingAgentConfig, ensure_spawn_settings
from coding_agent.web.bundle import BundleError
from coding_agent.updates import (
    UpdateDecision,
    check_for_update,
    installed_version,
    is_newer,
    pypi_tool_install,
    startup_update_check,
)

# The real apply_update; the root conftest swaps the module's for one that
# fails the test, so only a test that also stubs subprocess.run calls this.
real_apply_update = updates.apply_update


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
        pypi_install=lambda: True,
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
        pypi_install=lambda: True,
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
        pypi_install=lambda: True,
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
        pypi_install=lambda: True,
        web_root=lambda: Path("web"),
    )
    assert decision.action == "updated"
    assert any("checksum mismatch" in m and "symphony web --update" in m for m in messages)


def test_importing_updates_does_not_load_the_web_bundle() -> None:
    probe = "import sys, coding_agent.updates; print('coding_agent.web.bundle' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


class FakeDistribution(Distribution):
    """An installed symphony-code with the given version and direct_url.json."""

    def __init__(self, version: str, direct_url: str | None) -> None:
        self.files_text = {"METADATA": f"Metadata-Version: 2.1\nName: symphony-code\nVersion: {version}\n"}
        if direct_url is not None:
            self.files_text["direct_url.json"] = direct_url

    def read_text(self, filename: str) -> str | None:
        return self.files_text.get(filename)

    def locate_file(self, path: str | os.PathLike[str]) -> Path:
        return Path("/nonexistent") / path


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str | None], str | None]:
    """Run installed_version as an installed package (no .git above it) with a fake dist."""
    monkeypatch.setattr(updates, "SOURCE_ROOT", tmp_path / "lib")

    def use(version: str, direct_url: str | None) -> str | None:
        monkeypatch.setattr(updates, "distribution", lambda _name: FakeDistribution(version, direct_url))
        return installed_version()

    return use


def test_source_checkout_is_never_an_installed_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This test itself runs from the checkout, which has a .git at SOURCE_ROOT.
    assert (updates.SOURCE_ROOT / ".git").exists()
    assert installed_version() is None
    (tmp_path / ".git").write_text("gitdir: elsewhere\n")  # a worktree's .git is a file
    monkeypatch.setattr(updates, "SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(updates, "distribution", lambda _name: FakeDistribution("0.0.1", None))
    assert installed_version() is None


def test_file_installs_are_skipped_and_index_installs_are_not(
    installed: Callable[[str, str | None], str | None],
) -> None:
    assert installed("0.0.1", None) == "0.0.1"
    assert installed("0.0.1", '{"url": "https://files.pythonhosted.org/x.whl", "archive_info": {}}') == "0.0.1"
    # `uv tool install .`, `pip install -e .` and `pip install dist/x.whl` all record a file:// url.
    assert installed("0.0.1", '{"url": "file:///src/symphony/coding_agent", "dir_info": {}}') is None
    assert installed("0.0.1", '{"url": "file:///src/symphony", "dir_info": {"editable": true}}') is None
    assert installed("0.0.1", '{"url": "file:///tmp/dist/symphony_code-0.0.1-py3-none-any.whl"}') is None
    assert installed("0.0.1", "not json") is None
    assert installed("0.0.0", None) is None


def uv_tool_list(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> list[list[str]]:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, returncode, stdout, "")

    monkeypatch.setattr(updates.subprocess, "run", run)
    return commands


def test_only_this_pypi_uv_tool_counts_as_updatable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    here = Path(sys.prefix).resolve()
    line = "symphony-code v0.0.1{required} ({env})\n- symphony ({env}/bin/symphony)\n"

    def listed(required: str, env: Path = here) -> bool:
        uv_tool_list(monkeypatch, "ruff v0.6.0 (/x/ruff)\n- ruff\n" + line.format(required=required, env=env))
        return pypi_tool_install()

    assert listed(" [required: ==0.0.1]")
    assert listed("")  # `uv tool install symphony-code`, no specifier
    assert not listed(" [required: file:///src/symphony/coding_agent]")
    assert not listed(" [required: git+https://github.com/Sarthakischauhan/symphony]")
    # A PyPI tool that is not the environment running now is someone else's install.
    assert not listed(" [required: ==0.0.1]", env=tmp_path / "tools" / "symphony-code")
    commands = uv_tool_list(monkeypatch, "No tools installed\n")
    assert not pypi_tool_install()
    assert commands == [["uv", "tool", "list", "--show-version-specifiers", "--show-paths"]]
    uv_tool_list(monkeypatch, "", returncode=2)
    assert not pypi_tool_install()

    def missing(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(updates.subprocess, "run", missing)
    assert not pypi_tool_install()


def test_a_newer_release_is_not_offered_to_a_non_pypi_install() -> None:
    decision = startup_update_check(
        {"updates": {"auto": True}},
        current=lambda: "0.0.1",
        latest=lambda: "0.0.2",
        prompt=lambda _current, _latest: pytest.fail("a non-PyPI install must not be asked"),
        install=lambda _target: pytest.fail("a non-PyPI install must not be replaced"),
        output=lambda message: pytest.fail(f"nothing to say: {message}"),
        enabled=True,
        pypi_install=lambda: False,
    )
    assert decision == UpdateDecision("continue", "0.0.1", "0.0.2")


def test_a_pypi_tool_install_upgrades_with_uv_and_never_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = uv_tool_list(monkeypatch, "")
    assert real_apply_update("0.0.2").returncode == 0
    assert commands == [["uv", "tool", "install", "--upgrade", "symphony-code==0.0.2"]]
    with pytest.raises(ValueError):
        real_apply_update("0.0.2 --index evil")
    assert commands == [["uv", "tool", "install", "--upgrade", "symphony-code==0.0.2"]]
    # No pip fallback: the old command builder is gone.
    assert "_update_command" not in vars(updates)


def test_tests_cannot_install_or_check_for_real() -> None:
    assert os.environ["SYMPHONY_NO_UPDATE_CHECK"] == "1"
    for name in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        assert Path(os.environ[name]).is_relative_to(Path(os.environ["HOME"]))
    with pytest.raises(pytest.fail.Exception, match="for real"):
        updates.apply_update("0.0.2")
    # The default install looks apply_update up at call time, so the guard holds there too.
    with pytest.raises(pytest.fail.Exception, match="for real"):
        startup_update_check(
            {"updates": {"auto": True}},
            current=lambda: "0.0.1",
            latest=lambda: "0.0.2",
            output=lambda _message: None,
            enabled=True,
            pypi_install=lambda: True,
        )
