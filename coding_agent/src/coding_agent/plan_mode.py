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
    allowed_tools: set[str] = field(default_factory=lambda: {"read_file", "search", "ask_user"})

    def begin(self, path: str | None = None) -> None:
        self.active, self.approved, self.plan_path = True, False, path
    def approve(self) -> None:
        if not self.active:
            raise RuntimeError("no active plan")
        self.approved = True
    def reset(self) -> None:
        self.active = self.approved = False
        self.plan_path = None
    def permits(self, tool_name: str) -> bool:
        return not self.active or self.approved or tool_name in self.allowed_tools

class PlanModeAddon(Addon):
    name = "plan-mode"
    def __init__(self, state: PlanModeState) -> None:
        self.state = state
    async def before_tool(self, *, tool_name: str, **_: Any) -> Optional[str]:
        if self.state.permits(tool_name):
            return None
        return "plan mode is active: approve the plan before using implementation tools"
    def fork_for_child(self, parent_harness: Any) -> "PlanModeAddon":
        del parent_harness
        return PlanModeAddon(self.state)
