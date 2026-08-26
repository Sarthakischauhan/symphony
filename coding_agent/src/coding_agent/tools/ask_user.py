"""Ask the human a clarifying question and wait for an answer."""

from __future__ import annotations

from typing import Any

from core_ai.providers.anthropic import Content
from core_harness.control_plane import ControlPlane
from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class AskUserArgs(ToolArgsModel):
    question: str = Field(..., min_length=1, description="Clarifying question to show the user.")
    choices: list[str] = Field(default_factory=list, description="Optional preset answers to present.")
    default: str = Field(default="", description="Optional suggested answer.")


class AskUserTool(WorkspaceTool):
    name = "ask_user"
    description = (
        "Ask the user a clarifying question during an interactive run and return their answer. "
        "Use when the task is ambiguous or blocked on a human decision. "
        "Keep the question concise and specific."
    )
    args_model = AskUserArgs

    async def run(
        self,
        question: str,
        choices: list[str] | None = None,
        default: str = "",
        control_plane: ControlPlane | None = None,
    ) -> str:
        question = question.strip()
        if not question:
            return "error: question must be a non-empty string"

        request = getattr(control_plane, "request_user_input", None)
        if not callable(request):
            return "error: interactive user questions require an interactive control plane"

        answer = await request(
            question=question,
            choices=list(choices),
            default=default,
        )
        answer = str(answer or "").strip()
        if not answer and default:
            return default
        return answer or ""
