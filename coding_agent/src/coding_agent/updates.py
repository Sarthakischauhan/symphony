"""Check the installed coding agent against the published PyPI release.

The check runs before the TUI starts. It compares the installed
``symphony-code`` version with the latest version published on PyPI. A
matching version continues silently. A newer release asks before installing,
unless ``updates.auto`` is true in ``~/.symphony/config.json``.

Only a uv tool install of the PyPI release is ever replaced. A run from a
source checkout, a local (``file://``) install, editable or not, and any
install ``uv tool list`` does not show as this PyPI tool are left alone:
rewriting a developer's build is not an update.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Callable, Mapping

PACKAGE = "symphony-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
TIMEOUT_SECONDS = 3.0
# The repository root when this module runs from a source checkout
# (``coding_agent/src/coding_agent/updates.py``). In an installed package it is
# a directory of the environment (``lib``), which has no ``.git``.
SOURCE_ROOT = Path(__file__).resolve().parents[3]

Prompt = Callable[[str, str], bool]


@dataclass(frozen=True)
class UpdateDecision:
    """What startup should do after comparing versions."""

    action: str
    current: str | None = None
    latest: str | None = None
    message: str = ""


def installed_version() -> str | None:
    """Return the installed release, or None when there is none to update.

    None for a run from a source checkout, for a local install (its
    ``direct_url.json`` names a ``file://`` url: a directory, editable or not,
    or a wheel file), and when the release cannot be identified.
    """
    if (SOURCE_ROOT / ".git").exists():
        return None
    try:
        dist = distribution(PACKAGE)
    except PackageNotFoundError:
        return None
    direct = dist.read_text("direct_url.json")
    if direct:
        try:
            origin = json.loads(direct)
        except json.JSONDecodeError:
            return None
        url = origin.get("url") if isinstance(origin, dict) else None
        if not isinstance(url, str) or url.startswith("file:"):
            return None
    value = dist.version
    if not value or value == "0.0.0":
        return None
    return value


def pypi_tool_install() -> bool:
    """Whether ``uv tool list`` shows this running symphony-code as a PyPI install.

    Its line must name no url requirement (``file://`` or ``git+https://``),
    only a version specifier or none, and its tool environment must be the one
    running now, so the upgrade replaces this install and nothing else.
    """
    command = ["uv", "tool", "list", "--show-version-specifiers", "--show-paths"]
    try:
        listed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    if listed.returncode != 0:
        return False
    for line in listed.stdout.splitlines():
        if not line.startswith(f"{PACKAGE} v"):
            continue
        required = line.partition(" [required: ")[2].partition("]")[0]
        environment = line.rpartition(" (")[2].removesuffix(")")
        return "://" not in required and Path(environment).resolve() == Path(sys.prefix).resolve()
    return False


def latest_version(
    opener: Callable[..., object] | None = None,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """Return the newest PyPI version, or None when PyPI cannot be reached."""
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    if opener is None:
        from coding_agent.tls import https_context

        def opener(request: urllib.request.Request, *, timeout: float) -> object:
            return urllib.request.urlopen(request, timeout=timeout, context=https_context())

    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    info = payload.get("info") if isinstance(payload, dict) else None
    latest = info.get("version") if isinstance(info, dict) else None
    return latest if isinstance(latest, str) and latest else None


def is_newer(latest: str, current: str) -> bool:
    """Return whether the published release is strictly newer.

    An older or equal installed release is a deliberate client choice. It must
    not be offered again on every startup. Build metadata does not count.
    """
    return _release(latest) > _release(current)


def _release(value: str) -> tuple[int, ...]:
    numbers = value.split("+", 1)[0].split(".", 3)
    parsed: list[int] = []
    for number in numbers:
        digits = ""
        for character in number:
            if not character.isdigit():
                break
            digits += character
        parsed.append(int(digits or "0"))
    return tuple(parsed)


def check_for_update(
    *,
    current: str | None,
    latest: str | None,
    auto: bool,
    enabled: bool = True,
) -> UpdateDecision:
    """Decide whether startup should ask, update, or continue."""
    if not enabled or current is None or latest is None or not is_newer(latest, current):
        return UpdateDecision("continue", current, latest)
    if auto:
        return UpdateDecision(
            "update",
            current,
            latest,
            f"Updating symphony-code {current} to {latest}.",
        )
    return UpdateDecision(
        "ask",
        current,
        latest,
        f"symphony-code {latest} is available (installed: {current}). Update now? [y/N] ",
    )


def apply_update(target: str) -> subprocess.CompletedProcess[str]:
    """Install one exact symphony-code release as the uv tool it already is.

    Only called once :func:`pypi_tool_install` holds; there is no pip path.
    """
    if not target or any(character.isspace() for character in target):
        raise ValueError(f"invalid release version: {target!r}")
    command = ["uv", "tool", "install", "--upgrade", f"{PACKAGE}=={target}"]
    return subprocess.run(command, check=False, text=True, capture_output=True)


def _screen_prompt(current: str, latest: str) -> bool:
    from coding_agent.tui.screens.update import ask_to_update

    return ask_to_update(current, latest)


def run_startup_update_check(*, unattended: bool = False) -> str:
    """Check the user config, then compare the installed package with PyPI.

    Unattended runs never prompt. They update only when automatic updates are
    already enabled and otherwise continue with the installed version.
    """
    from coding_agent.config import ensure_spawn_settings, symphony_dir

    config = ensure_spawn_settings(symphony_dir())
    if unattended and not config.updates.auto:
        return "continue"
    return startup_update_check({"updates": config.updates.model_dump()}).action


def startup_update_check(
    config: Mapping[str, object],
    *,
    current: Callable[[], str | None] = installed_version,
    latest: Callable[[], str | None] = latest_version,
    prompt: Prompt | None = None,
    install: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
    output: Callable[[str], None] = print,
    enabled: bool | None = None,
    install_web: Callable[[str, Path], Path] | None = None,
    web_root: Callable[[], Path] | None = None,
    pypi_install: Callable[[], bool] = pypi_tool_install,
) -> UpdateDecision:
    """Run the pre-start check described by ``updates`` in the user config.

    After the package updates, the matching Symphony Web bundle is installed
    and made current. A failed bundle install keeps the old bundle and only
    warns: the package update itself already succeeded. ``install_web`` and
    ``web_root`` default to :mod:`coding_agent.web.bundle`, imported only once
    an update is under way. A newer release is offered only when
    ``pypi_install`` confirms a uv tool install from PyPI; ``install``
    defaults to :func:`apply_update`, looked up at call time.
    """
    settings = config.get("updates") if isinstance(config.get("updates"), Mapping) else {}
    if enabled is None:
        enabled = os.environ.get("SYMPHONY_NO_UPDATE_CHECK", "").strip().lower() not in {"1", "true", "yes"}
    decision = check_for_update(
        current=current(),
        latest=latest() if enabled else None,
        auto=bool(settings.get("auto")),
        enabled=enabled and settings.get("enabled", True) is not False,
    )
    if decision.action == "continue":
        return decision
    target = decision.latest
    if target is None:
        # check_for_update names the version for every action except continue.
        return UpdateDecision("continue", decision.current)
    if not pypi_install():
        # A pip, git or local install, or another tool environment: not ours to replace.
        return UpdateDecision("continue", decision.current, decision.latest)
    accepted = decision.action == "update"
    if decision.action == "ask":
        ask = prompt or _screen_prompt
        try:
            accepted = bool(ask(decision.current or "", target))
        except EOFError:
            accepted = False
        if not accepted:
            output(f"Continuing with symphony-code {decision.current}.")
            return UpdateDecision("continue", decision.current, decision.latest)
    else:
        output(decision.message)
    result = (install or apply_update)(target)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        output(f"Update to {decision.latest} failed; continuing with {decision.current}.")
        if detail:
            output(detail)
        return UpdateDecision("failed", decision.current, decision.latest, detail)
    from coding_agent.web import bundle

    try:
        if install_web is None:
            install_web = bundle.install
        install_web(target, web_root() if web_root is not None else bundle.bundle_root())
    except bundle.BundleError as exc:
        output(f"Symphony Web {decision.latest} was not installed ({exc}); run `symphony web --update` to retry.")
    output(f"Updated symphony-code to {decision.latest}. Restart `symphony` to use it.")
    return UpdateDecision("updated", decision.current, decision.latest)
