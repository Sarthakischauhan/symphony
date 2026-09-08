"""Tool for entering the gated plan phase."""
from __future__ import annotations

from pydantic import BaseModel
from core_harness.events import EventSink
from coding_agent.tools.base import WorkspaceTool


class EmptyArgs(BaseModel):
    pass


class EnterPlanModeTool(WorkspaceTool):
    name = "enter_plan_mode"
    description = "Request user approval to enter the gated planning phase."
    args_model = EmptyArgs

    def __init__(self, workspace, state, agent=None):
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
