"""Slash-command definitions and the temporary built-in model catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    argument: str = ""

    @property
    def usage(self) -> str:
        return f"/{self.name}{f' {self.argument}' if self.argument else ''}"


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    description: str


# This is intentionally isolated from the dispatcher. Replace this tuple with a
# registry/provider discovery result when ModelRegistry grows a model-list API.
MODEL_CATALOG = (
    ModelOption("openai:gpt-5.4-mini", "GPT-5.4 mini", "Thinking model"),
    ModelOption("openai:gpt-4o-mini", "GPT-4o mini", "Fast and economical"),
    ModelOption("openai:gpt-4.1-mini", "GPT-4.1 mini", "Fast coding model"),
    ModelOption("openai:gpt-4.1", "GPT-4.1", "Most capable in this catalog"),
)


SLASH_COMMANDS = (
    SlashCommand("model", "View or switch the active model", "[model]"),
    SlashCommand("new", "Start a fresh conversation"),
    SlashCommand("compact", "Keep recent messages and compact saved context"),
    SlashCommand("status", "Show session, model, and context details"),
    SlashCommand("clear", "Clear the visible transcript"),
    SlashCommand("help", "Show available slash commands"),
    SlashCommand("quit", "Exit Symphony"),
)


def command_matches(value: str) -> tuple[SlashCommand, ...]:
    """Return command suggestions for the current composer value."""
    if not value.startswith("/") or " " in value:
        return ()
    prefix = value[1:].lower()
    return tuple(command for command in SLASH_COMMANDS if command.name.startswith(prefix))


def find_model(value: str, models: Iterable[ModelOption] = MODEL_CATALOG) -> Optional[ModelOption]:
    """Resolve a full id, provider-less id, or unambiguous display label."""
    needle = value.strip().lower()
    if not needle:
        return None
    matches = [
        model
        for model in models
        if needle
        in {
            model.id.lower(),
            model.id.split(":", 1)[-1].lower(),
            model.label.lower(),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def model_matches(
    value: str, models: Iterable[ModelOption] = MODEL_CATALOG
) -> tuple[ModelOption, ...]:
    """Filter model choices by id, provider-less id, or label."""
    needle = value.strip().lower()
    return tuple(
        model
        for model in models
        if not needle
        or needle in model.id.lower()
        or needle in model.label.lower()
    )
