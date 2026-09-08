"""Tool for presenting the saved plan for user disposition."""
from __future__ import annotations

from pydantic import BaseModel
from coding_agent.tools.base import WorkspaceTool


class EmptyArgs(BaseModel):
    pass


class ExitPlanModeTool(WorkspaceTool):
    name = "exit_plan_mode"
    description = "Show the saved plan and ask whether to build it or request changes."
    args_model = EmptyArgs

    def __init__(self, workspace, state):
        self.state = state
        super().__init__(workspace)

    def run(self) -> str:
        if not self.state.active:
            return "error: plan mode is not active"
        path = self.state.plan_path
        if not path:
            return "error: no plan file is active"
        try:
            content = open(path, encoding="utf-8").read()
        except OSError as exc:
            return f"error: could not read plan: {exc}"
        return f"plan ready for review at {path}\n{content}"
