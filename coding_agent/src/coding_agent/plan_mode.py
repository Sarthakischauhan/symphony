"""Explicit plan-mode state and harness tool gate."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
from core_harness.addons.addon import Addon

@dataclass
class PlanModeState:
    active: bool = False
    approved: bool = False
    plan_path: str | None = None
    allowed_tools: set[str] = field(default_factory=lambda: {"read_file", "search", "ask_user", "bash", "memory"})

    def begin(self, path: str | None = None) -> None:
        self.active, self.approved, self.plan_path = True, False, path

    def set_plan_path(self, path: str | None) -> None:
        self.plan_path = path
    def approve(self) -> None:
        if not self.active:
            raise RuntimeError("no active plan")
        self.approved = True
    def reset(self) -> None:
        self.active = self.approved = False
        self.plan_path = None
    def permits(self, tool_name: str, *, target: str | None = None) -> bool:
        if not self.active or self.approved or tool_name in self.allowed_tools:
            return True
        if tool_name in {"write_file", "patch"} and self.plan_path and target:
            return target == self.plan_path
        return False

class PlanModeAddon(Addon):
    name = "plan-mode"
    def __init__(self, state: PlanModeState) -> None:
        self.state = state
    async def before_tool(self, *, tool_name: str, **kwargs: Any) -> Optional[str]:
        args = kwargs.get("arguments") or kwargs.get("args") or {}
        target = args.get("path") if isinstance(args, dict) else None
        if self.state.permits(tool_name, target=target):
            return None
        return "plan mode is active: approve the plan before using implementation tools"
    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None
