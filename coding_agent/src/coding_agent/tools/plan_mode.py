"""Explicit tools for entering and leaving product plan mode."""
from __future__ import annotations
from pydantic import BaseModel
from coding_agent.tools.base import WorkspaceTool

class EmptyArgs(BaseModel):
    pass

class EnterPlanModeTool(WorkspaceTool):
    name = "enter_plan_mode"
    description = "Request entry into the gated planning phase."
    args_model = EmptyArgs
    def __init__(self, workspace, state):
        self.state = state
        super().__init__(workspace)
    def run(self) -> str:
        self.state.begin()
        return "plan mode requested; continue by producing a plan"

class ExitPlanModeTool(WorkspaceTool):
    name = "exit_plan_mode"
    description = "Request leaving plan mode after the plan is complete."
    args_model = EmptyArgs
    def __init__(self, workspace, state):
        self.state = state
        super().__init__(workspace)
    def run(self) -> str:
        self.state.reset()
        return "plan mode exited; the user may approve the plan for a build turn"
