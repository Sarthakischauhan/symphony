"""Product approval rules, independent of the TUI.

The harness asks ``approve_tool_call`` before running a tool. Coding-agent
policy lives here: which tools need a prompt, how answers map to allow/deny,
and how a child plane is forked so background work does not block on the
parent's prompts. The TUI only renders the question and returns the answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, Union, runtime_checkable

from core_harness import ControlPlane

from coding_agent.config import ApprovalConfig

ALLOW_ONCE = "Allow once"
ALLOW_ALWAYS = "Always allow"
DENY = "Deny"
APPROVAL_CHOICES = (ALLOW_ONCE, ALLOW_ALWAYS, DENY)


class ApprovalPolicy:
    """Path-aware rules. Callers pass the current ``ApprovalConfig``."""

    def __init__(self, workspace: Union[str, Path]) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    def prompt_for(
        self,
        config: ApprovalConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """Return the question to ask, or ``""`` if the call is allowed."""
        if config.mode == "always_allow":
            return ""
        if tool_name == "bash" and config.require_for_bash:
            command = str(arguments.get("command") or "").strip()
            return f"Allow bash command once?\n`{command}`"
        if tool_name in {"write_file", "generate_image"}:
            path = str(arguments.get("path") or "").strip()
            if config.require_for_overwrite and path and self._exists(path):
                return f"Overwrite existing file `{path}`?"
            return ""
        if tool_name == "patch" and config.require_for_broad_patch:
            path = str(arguments.get("path") or "").strip()
            old = str(arguments.get("old_str") or arguments.get("old_string") or "")
            replace_all = bool(arguments.get("replace_all"))
            if replace_all or len(old) > config.broad_patch_chars:
                kind = "global" if replace_all else "large"
                return f"Apply a {kind} patch to `{path}`?"
        return ""

    def interpret(
        self,
        config: ApprovalConfig,
        answer: str,
    ) -> Tuple[bool, bool]:
        """Map a UI answer to ``(allowed, promote_to_always_allow)``."""
        if config.mode == "always_allow":
            return True, False
        normalized = answer.strip().lower()
        if normalized == ALLOW_ALWAYS.lower():
            return True, True
        return normalized in config.allow_answers, False

    def _exists(self, path: str) -> bool:
        try:
            candidate = Path(path).expanduser()
            target = (
                candidate.resolve()
                if candidate.is_absolute()
                else (self.workspace / candidate).resolve()
            )
            return target.exists()
        except OSError:
            return False


@runtime_checkable
class ForkableControlPlane(Protocol):
    """Application planes that can mint an isolated child plane."""

    approvals: ApprovalConfig

    def fork(self, *, approvals: Optional[ApprovalConfig] = None) -> ControlPlane: ...


def child_control_plane(plane: ControlPlane) -> Optional[ControlPlane]:
    """Fork a child plane that does not prompt.

    Children in ``symphony-code`` run without per-tool approval prompts. That
    is current product policy, documented in ``SECURITY.md``. Planes that
    cannot fork (library ``EventControlPlane``) share the parent plane.
    """
    if not isinstance(plane, ForkableControlPlane):
        return None
    approvals = plane.approvals.model_copy(update={"mode": "always_allow"})
    return plane.fork(approvals=approvals)


__all__ = [
    "ALLOW_ALWAYS",
    "ALLOW_ONCE",
    "APPROVAL_CHOICES",
    "ApprovalPolicy",
    "DENY",
    "ForkableControlPlane",
    "child_control_plane",
]
