"""Enter and leave the gated plan phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core_harness.events import EventSink
from coding_agent.tools.base import WorkspaceTool


class EmptyArgs(BaseModel):
    pass


class EnterPlanModeTool(WorkspaceTool):
    name = "enter_plan_mode"
    description = "Request user approval to enter the gated planning phase."
    args_model = EmptyArgs

    def __init__(self, workspace: str | Path, state: Any, agent: Any = None) -> None:
        self.state = state
        self.agent = agent
        super().__init__(workspace)

    async def run(self, sink: EventSink | None = None) -> str:
        if sink is None:
            return "error: entering plan mode requires user approval"
        answer = await sink.request_user_input(
            question="Enter plan mode? Only the plan file may be written.",
            choices=["Allow", "Decline"],
            default="Allow",
        )
        if str(answer).strip().casefold() not in {"allow", "yes", "y", "approve"}:
            return "plan mode declined"
        self.state.begin()
        if self.agent is not None:
            self.agent.set_mode("plan")
        return "plan mode approved; continue by producing a plan"


class ExitPlanModeTool(WorkspaceTool):
    name = "exit_plan_mode"
    description = "Show the saved plan and ask whether to build it or request changes."
    args_model = EmptyArgs

    def __init__(self, workspace: str | Path, state: Any) -> None:
        self.state = state
        super().__init__(workspace)

    def run(self) -> str:
        if not self.state.active:
            return "error: plan mode is not active"
        path = self.state.plan_path
        if not path:
            return "error: no plan file is active"
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            return f"error: could not read plan: {exc}"
        return f"plan ready for review at {path}\n{content}"


__all__ = ["EnterPlanModeTool", "ExitPlanModeTool"]
