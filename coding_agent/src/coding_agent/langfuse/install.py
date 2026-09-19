"""Install the optional Langfuse SDK into the current interpreter."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

LANGFUSE_PACKAGE = "langfuse>=3.0.0"
INSTALL_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class InstallResult:
    installed: bool
    already_present: bool
    message: str


def langfuse_available() -> bool:
    """Return True when ``import langfuse`` succeeds in this process."""
    try:
        importlib.import_module("langfuse")
        return True
    except ImportError:
        return False


def ensure_langfuse_installed() -> InstallResult:
    """Install ``langfuse`` if missing. No-op when the import already works."""
    if langfuse_available():
        return InstallResult(True, True, "Langfuse SDK already installed")
    error = _install()
    importlib.invalidate_caches()
    if langfuse_available():
        return InstallResult(True, False, "Installed Langfuse SDK")
    detail = error or "langfuse is not importable after install"
    return InstallResult(
        False,
        False,
        f"Could not install the Langfuse SDK ({detail}). "
        "Install it with: uv sync --package symphony-code --extra langfuse",
    )


def _install() -> str:
    commands: list[list[str]] = []
    uv = shutil.which("uv")
    if uv:
        commands.append([uv, "pip", "install", LANGFUSE_PACKAGE, "--python", sys.executable])
    commands.append([sys.executable, "-m", "pip", "install", LANGFUSE_PACKAGE])
    errors: list[str] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_SECONDS,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{command[0]} timed out")
            continue
        except OSError as exc:
            errors.append(f"{command[0]}: {exc}")
            continue
        if completed.returncode == 0:
            return ""
        detail = (completed.stderr or completed.stdout or "").strip()
        errors.append(detail.splitlines()[-1] if detail else f"{command[0]} exit {completed.returncode}")
    return "; ".join(errors[:2]) if errors else "no installer available"


__all__ = ["InstallResult", "ensure_langfuse_installed", "langfuse_available"]
