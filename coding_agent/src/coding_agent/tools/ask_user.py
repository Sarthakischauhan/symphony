"""Ask the human a clarifying question and wait for an answer."""

from __future__ import annotations

import re

from core_harness.events import EventSink
from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

NO_HUMAN_ANSWER = "no human available; pick the safest reasonable option and continue"

# Answers that skip a hook or verification step (git --no-verify, "bypass the pre-commit hook",
# "skip the tests"). The user may still pick one, but it is never the default or preselected.
VERIFICATION_BYPASS = re.compile(
    r"--no-verify|\bno[- ]verify\b"
    r"|\b(?:bypass|skip|disable|ignore|override)\w*\b[^.\n]{0,40}?"
    r"\b(?:hooks?|pre-commit|pre-push|husky|verification|verify|checks?|ci|lint\w*|tests?|gpg)\b",
    re.IGNORECASE,
)


def demote_verification_bypass(choices: list[str], default: str) -> tuple[list[str], str]:
    """Never default to or preselect a hook/verification bypass.

    Bypass choices move after the others (UIs preselect the first choice when there is
    no default). If every choice is a bypass, no preset is offered and the user answers freely.
    """
    safe = [choice for choice in choices if not VERIFICATION_BYPASS.search(choice)]
    bypass = [choice for choice in choices if VERIFICATION_BYPASS.search(choice)]
    if default and VERIFICATION_BYPASS.search(default):
        default = ""
    return (safe + bypass if safe else []), default


class AskUserArgs(ToolArgsModel):
    question: str = Field(..., min_length=1, description="Clarifying question to show the user.")
    choices: list[str] = Field(default_factory=list, description="Optional preset answers to present.")
    default: str = Field(default="", description="Optional suggested answer.")


class AskUserTool(WorkspaceTool):
    name = "ask_user"
    description = (
        "Ask the user a clarifying question during an interactive run and return their answer. "
        "Use when the task is ambiguous or blocked on a human decision. "
        "Keep the question concise and specific. "
        "Never make skipping hooks, tests, or other verification (for example --no-verify) "
        "the default or first choice; fix the failure or ask how to proceed instead."
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
            return "error: question must be a non-empty string"

        choices, default = demote_verification_bypass(list(choices or []), default)
        if self.unattended:
            # ApprovalAddon records the auto_decision; never block on a human here.
            # Without a human there is nobody to approve a bypass, so it is not offered at all.
            choices = [choice for choice in choices if not VERIFICATION_BYPASS.search(choice)]
            hints = [f"default: {default}"] if default else []
            hints += [f"choices: {', '.join(choices)}"] if choices else []
            return "\n".join([NO_HUMAN_ANSWER, *hints])

        if sink is None:
            return "error: interactive user questions require an interactive control plane"

        answer = await sink.interaction.request_user_input(
            question=question,
            choices=list(choices),
            default=default,
        )
        answer = str(answer or "").strip()
        if not answer and default:
            return default
        return answer or ""
