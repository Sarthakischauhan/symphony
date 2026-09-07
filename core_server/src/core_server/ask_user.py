"""``ask_user`` tool for server-hosted harness runs."""

from __future__ import annotations

from typing import Any

from core_harness import Tool


ASK_USER_PARAMETERS = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "Concise, specific question to show the user.",
        },
        "choices": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional preset answers to present.",
        },
        "default": {
            "type": "string",
            "description": "Optional suggested answer used when the user submits an empty answer.",
        },
    },
    "required": ["question"],
    "additionalProperties": False,
}


async def ask_user(
    question: str,
    choices: list[str] | None = None,
    default: str = "",
    *,
    sink: Any = None,
) -> str:
    """Emit a question for the user; their reply is the next user message."""
    question = question.strip()
    if not question:
        return "error: question must be a non-empty string"
    if sink is None:
        return "error: ask_user requires a control plane"

    await sink.request_user_input(
        question=question,
        choices=list(choices or ()),
        default=default,
    )
    return "Question sent to the user. Wait for their next message before continuing."


def build_ask_user_tool() -> Tool:
    """Create the built-in interactive question tool."""
    return Tool(
        ask_user,
        name="ask_user",
        description=(
            "Ask the user a concise, specific clarifying question during an interactive run. "
            "This emits a question_asked event; the user's reply arrives as a later user message. "
            "Use it only when blocked by an ambiguity or decision that requires user input."
        ),
        parameters=ASK_USER_PARAMETERS,
    )
