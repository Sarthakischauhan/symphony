"""Product approval rules, independent of the TUI.

The harness calls ``Addon.before_tool`` before running a tool. This add-on
implements symphony-code policy: which tools need a prompt, how answers map
to allow/deny, and that children do not inherit the gate. The TUI only
renders the question and returns the answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from core_harness import Addon, EventSink

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
    ) -> tuple[bool, bool]:
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


class ApprovalAddon(Addon):
    """Gate tools through :class:`ApprovalPolicy` before the harness runs them.

    ``fork_for_child`` returns ``None`` so spawned children skip this gate.
    That is current product policy, documented in ``SECURITY.md``.
    """

    name = "approval"

    def __init__(self, workspace: Union[str, Path], plane: EventSink) -> None:
        self.policy = ApprovalPolicy(workspace)
        self.plane = plane

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None

    async def before_tool(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        sink: Optional[EventSink] = None,
        **_: Any,
    ) -> Optional[str]:
        approvals = getattr(self.plane, "approvals", None)
        if approvals is None:
            return None
        prompt = self.policy.prompt_for(approvals, tool_name, arguments)
        if not prompt:
            return None
        ask_on = sink or self.plane
        answer = await ask_on.request_user_input(
            question=prompt,
            choices=APPROVAL_CHOICES,
            default=ALLOW_ONCE,
            kind="approval",
            metadata={"tool_name": tool_name},
        )
        allowed, promote = self.policy.interpret(self.plane.approvals, answer)
        if promote:
            setter = getattr(self.plane, "set_approval_mode", None)
            if callable(setter):
                setter("always_allow")
        if not allowed:
            return "tool call denied by user"
        return None


__all__ = [
    "ALLOW_ALWAYS",
    "ALLOW_ONCE",
    "APPROVAL_CHOICES",
    "ApprovalAddon",
    "ApprovalPolicy",
    "DENY",
]
