"""Check the installed coding agent against the published PyPI release.

The check runs before the TUI starts. It compares the installed
``symphony-code`` version with the latest version published on PyPI. A
matching version continues silently. A newer release asks before installing,
unless ``updates.auto`` is true in ``~/.symphony/config.json``. An editable
or unknown install is left alone: rewriting a source checkout is not an
update.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Callable, Mapping

PACKAGE = "symphony-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
TIMEOUT_SECONDS = 3.0

Prompt = Callable[[str, str], bool]


@dataclass(frozen=True)
class UpdateDecision:
    """What startup should do after comparing versions."""

    action: str
    current: str | None = None
    latest: str | None = None
    message: str = ""


def installed_version() -> str | None:
    """Return the installed release, or None when it cannot be identified."""
    try:
        dist = distribution(PACKAGE)
        value = version(PACKAGE)
    except PackageNotFoundError:
        return None
    editable = dist.read_text("direct_url.json")
    if editable:
        try:
            if json.loads(editable).get("dir_info", {}).get("editable"):
                return None
        except json.JSONDecodeError:
            return None
    if not value or value == "0.0.0":
        return None
    return value


def latest_version(
    opener: Callable[..., object] | None = None,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """Return the newest PyPI version, or None when PyPI cannot be reached."""
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
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
    """Install one exact symphony-code release with the tool that installed it."""
    if not target or any(character.isspace() for character in target):
        raise ValueError(f"invalid release version: {target!r}")
    command = _update_command(target)
    return subprocess.run(command, check=False, text=True, capture_output=True)


def _update_command(target: str) -> list[str]:
    specifier = f"{PACKAGE}=={target}"
    if _installed_with_uv():
        return ["uv", "tool", "install", "--upgrade", specifier]
    return [sys.executable, "-m", "pip", "install", "--upgrade", specifier]


def _installed_with_uv() -> bool:
    try:
        location = Path(distribution(PACKAGE).locate_file(""))
    except PackageNotFoundError:
        return False
    return "uv" in location.parts


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
    return startup_update_check(config.updates.model_dump()).action


def startup_update_check(
    config: Mapping[str, object],
    *,
    current: Callable[[], str | None] = installed_version,
    latest: Callable[[], str | None] = latest_version,
    prompt: Prompt | None = None,
    install: Callable[[str], subprocess.CompletedProcess[str]] = apply_update,
    output: Callable[[str], None] = print,
    enabled: bool | None = None,
) -> UpdateDecision:
    """Run the pre-start check described by ``updates`` in the user config."""
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
    accepted = decision.action == "update"
    if decision.action == "ask":
        ask = prompt or _screen_prompt
        try:
            accepted = bool(ask(decision.current or "", decision.latest or ""))
        except EOFError:
            accepted = False
        if not accepted:
            output(f"Continuing with symphony-code {decision.current}.")
            return UpdateDecision("continue", decision.current, decision.latest)
    else:
        output(decision.message)
    result = install(decision.latest or "")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        output(f"Update to {decision.latest} failed; continuing with {decision.current}.")
        if detail:
            output(detail)
        return UpdateDecision("failed", decision.current, decision.latest, detail)
    output(f"Updated symphony-code to {decision.latest}. Restart `symphony` to use it.")
    return UpdateDecision("updated", decision.current, decision.latest)
