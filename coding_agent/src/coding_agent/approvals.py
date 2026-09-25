"""Product approval rules, independent of the TUI.

The harness calls ``Addon.before_tool`` before running a tool. This add-on
implements symphony-code policy: durable deny/allow rules, which tools need
a prompt, how answers map to allow/deny, and that children do not inherit
the gate (except the deny rules in unattended runs). The TUI only renders the
question and returns the answer. Unattended runs never prompt: each decision a
human would have made is emitted as an ``auto_decision`` event instead.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from core_harness import Addon, EventSink

from coding_agent.config import ApprovalConfig

ALLOW_ONCE = "Allow once"
ALLOW_ALWAYS = "Always allow"
DENY = "Deny"
APPROVAL_CHOICES = (ALLOW_ONCE, ALLOW_ALWAYS, DENY)
AUTO_DECISION = "auto_decision"
RULE_SUBJECTS = {"bash": "command", "write_file": "path", "patch": "path", "generate_image": "path"}


def matching_rule(patterns: Sequence[str], tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """First pattern matching the bash command (or write/patch path), if any."""
    field = RULE_SUBJECTS.get(tool_name)
    subject = str(arguments.get(field) or "").strip() if field else ""
    return next((pattern for pattern in patterns if subject and fnmatchcase(subject, pattern)), None)


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
        """Return the question to ask, or ``""`` if the call is allowed.

        Deny rules are not a prompt; ``ApprovalAddon`` checks them first.
        """
        if config.mode == "always_allow" or matching_rule(config.allow, tool_name, arguments):
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
    """Gate tools through deny rules, then :class:`ApprovalPolicy` prompts.

    Deny rules apply in every mode. ``fork_for_child`` returns ``None`` so
    spawned children skip this gate, except in unattended runs where children
    get a deny-only fork. That is product policy, documented in ``SECURITY.md``.
    """

    name = "approval"

    def __init__(
        self,
        workspace: Union[str, Path],
        plane: EventSink,
        *,
        approvals: Optional[ApprovalConfig] = None,
        unattended: bool = False,
        deny_only: bool = False,
    ) -> None:
        self.policy = ApprovalPolicy(workspace)
        self.plane = plane
        self.approvals = approvals
        self.unattended = unattended
        self.deny_only = deny_only

    def fork_for_child(self, parent_harness: Any) -> Optional["ApprovalAddon"]:
        del parent_harness
        if not self.unattended:
            return None
        return ApprovalAddon(
            self.policy.workspace, self.plane,
            approvals=self.approvals, unattended=True, deny_only=True,
        )

    async def before_tool(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        sink: Optional[EventSink] = None,
        emit: Any = None,
        **_: Any,
    ) -> Optional[str]:
        approvals = getattr(self.plane, "approvals", None) or self.approvals
        if approvals is None:
            return None
        emit = emit or self.plane.emit
        rule = matching_rule(approvals.deny, tool_name, arguments)
        if rule:
            await emit(AUTO_DECISION, {"kind": "approval", "tool": tool_name, "decision": "deny", "rule": rule})
            return f"tool call denied by rule {rule!r}"
        if self.unattended and tool_name == "ask_user":
            await emit(AUTO_DECISION, {"kind": "ask_user", "question": str(arguments.get("question") or "")})
        if self.deny_only:
            return None
        prompt = self.policy.prompt_for(approvals, tool_name, arguments)
        if not prompt:
            return None
        if self.unattended:
            await emit(AUTO_DECISION, {"kind": "approval", "tool": tool_name, "decision": "allow", "rule": "unattended"})
            return None
        ask_on = sink or self.plane
        answer = await ask_on.request_user_input(
            question=prompt,
            choices=APPROVAL_CHOICES,
            default=ALLOW_ONCE,
            kind="approval",
            metadata={"tool_name": tool_name},
        )
        allowed, promote = self.policy.interpret(approvals, answer)
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
    "AUTO_DECISION",
    "ApprovalAddon",
    "ApprovalPolicy",
    "DENY",
    "matching_rule",
]
