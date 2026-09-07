"""Explicit plan-mode state and tool gating."""
from __future__ import annotations
from dataclasses import dataclass, field

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
