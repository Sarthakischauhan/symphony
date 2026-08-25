"""Slash-command definitions and lookup helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from core_ai import list_models


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


@dataclass(frozen=True)
class ModeOption:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class PlanOption:
    id: str
    label: str
    description: str


MODE_CATALOG = (
    ModeOption("build", "Build", "Read, edit, and run code"),
    ModeOption("plan", "Plan", "Inspect and write a plan only"),
)

SLASH_COMMANDS = (
    SlashCommand("model", "View or switch the active model", "[model]"),
    SlashCommand("mode", "View or switch between build and plan", "[mode]"),
    SlashCommand("plan", "Choose and open a workspace plan", "[plan]"),
    SlashCommand("new", "Start a fresh conversation"),
    SlashCommand("reload", "Reload configuration from .env"),
    SlashCommand("compact", "Keep recent messages and compact saved context"),
    SlashCommand("status", "Show session, model, and context details"),
    SlashCommand("learning", "Open markdown-rendered agent learnings"),
    SlashCommand("diff", "Open the current workspace diff in a modal"),
    SlashCommand("clear", "Clear the visible transcript"),
    SlashCommand("help", "Show available slash commands"),
    SlashCommand("quit", "Exit Symphony"),
)


def command_matches(value: str) -> tuple[SlashCommand, ...]:
    if not value.startswith("/") or " " in value:
        return ()
    prefix = value[1:].lower()
    return tuple(command for command in SLASH_COMMANDS if command.name.startswith(prefix))


def model_options(providers: Iterable[str] | None = None) -> tuple[ModelOption, ...]:
    """Build TUI choices from the core_ai catalog, optionally by provider."""
    source = list_models() if providers is None else tuple(
        model for provider in providers for model in list_models(provider)
    )
    return tuple(
        ModelOption(
            id=model.full_id,
            label=model.id,
            description=f"{model.provider} · {model.api.replace('_', ' ')}",
        )
        for model in source
    )


def find_model(
    value: str,
    models: Iterable[ModelOption] | None = None,
) -> Optional[ModelOption]:
    models = model_options() if models is None else models
    needle = value.strip().lower()
    if not needle:
        return None
    matches = [
        model for model in models
        if needle in {model.id.lower(), model.id.split(":", 1)[-1].lower(), model.label.lower()}
    ]
    return matches[0] if len(matches) == 1 else None


def model_matches(
    value: str,
    models: Iterable[ModelOption] | None = None,
) -> tuple[ModelOption, ...]:
    models = model_options() if models is None else models
    needle = value.strip().lower()
    return tuple(model for model in models if not needle or needle in model.id.lower() or needle in model.label.lower())


def find_mode(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> Optional[ModeOption]:
    needle = value.strip().lower()
    matches = [mode for mode in modes if needle in {mode.id.lower(), mode.label.lower()}]
    return matches[0] if len(matches) == 1 else None


def mode_matches(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> tuple[ModeOption, ...]:
    needle = value.strip().lower()
    return tuple(mode for mode in modes if not needle or needle in mode.id.lower() or needle in mode.label.lower())
