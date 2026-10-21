"""Ask the human a clarifying question and wait for an answer."""

from __future__ import annotations


from core_harness.events import EventSink
from core_harness.tools import current_tool_call_id
from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

NO_HUMAN_ANSWER = "no human available; pick the safest reasonable option and continue"


class AskUserFailed(RuntimeError):
    """No human answered. The harness reports any raised error as ``status="error"``.

    The message is what the model reads: for an unattended run it carries the
    default and choices so the model picks one and keeps going.
    """


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

    def __init__(self, workspace: str, *, unattended: bool = False) -> None:
        self.unattended = unattended
        super().__init__(workspace)

    async def run(
        self,
        question: str,
        choices: list[str] | None = None,
        default: str = "",
        sink: EventSink | None = None,
    ) -> str:
        question = question.strip()
        if not question:
            raise AskUserFailed("question must be a non-empty string")

        if self.unattended:
            # ApprovalAddon records the auto_decision; never block on a human here.
            hints = [f"default: {default}"] if default else []
            hints += [f"choices: {', '.join(choices)}"] if choices else []
            raise AskUserFailed("\n".join([NO_HUMAN_ANSWER, *hints]))

        if sink is None:
            raise AskUserFailed("interactive user questions require an interactive control plane")

        # The call id lets a host match the question to this call's
        # tool_execution_completed, like an approval's metadata.
        call_id = current_tool_call_id.get()
        answer = await sink.interaction.request_user_input(
            question=question,
            choices=list(choices),
            default=default,
            metadata={"tool_call_id": call_id} if call_id else None,
        )
        answer = str(answer or "").strip()
        if not answer and default:
            return default
        return answer or ""
