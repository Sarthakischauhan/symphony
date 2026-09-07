"""Slash-command catalogs and option matching."""

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
class EffortOption:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class PlanOption:
    id: str
    label: str
    description: str


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


EFFORT_CATALOG = (
    EffortOption("default", "Default", "Use Symphony's balanced default"),
    EffortOption("none", "None", "Fastest · no deliberate reasoning"),
    EffortOption("low", "Low", "Fast · lightweight reasoning"),
    EffortOption("medium", "Medium", "Balanced speed and depth"),
    EffortOption("high", "High", "Deeper reasoning"),
    EffortOption("xhigh", "Extra high", "Extended reasoning"),
    EffortOption("max", "Maximum", "Deepest reasoning · GPT-5.6"),
)
EFFORTS = tuple(option.id for option in EFFORT_CATALOG)

MODE_CATALOG = (
    ModeOption("build", "Build", "Read, edit, and run code"),
    ModeOption("plan", "Plan", "Inspect and write a plan only"),
)

SLASH_COMMANDS = (
    SlashCommand("model", "View or switch the active model", "[model]"),
    SlashCommand("mode", "View or switch between build and plan", "[mode]"),
    SlashCommand("effort", "Set model reasoning effort", "[level]"),
    SlashCommand("plan", "Choose and open a workspace plan", "[plan]"),
    SlashCommand("provider", "Add or update a provider API key", "[name]"),
    SlashCommand("new", "Start a fresh conversation"),
    SlashCommand("reload", "Reload configuration from .env"),
    SlashCommand("compact", "Keep recent messages and compact saved context"),
    SlashCommand("status", "Show session, model, and context details"),
    SlashCommand("context", "Inspect stored vs sent context"),
    SlashCommand("learning", "Open markdown-rendered agent learnings"),
    SlashCommand("installed", "View installed skills and plugins"),
    SlashCommand("diff", "Open the current workspace diff in a modal"),
    SlashCommand("clear", "Clear the visible transcript"),
    SlashCommand("help", "Show available slash commands"),
    SlashCommand("quit", "Exit Symphony"),
)


def command_matches(value: str, *, include_effort: bool = True) -> tuple[SlashCommand, ...]:
    if not value.startswith("/") or " " in value:
        return ()
    prefix = value[1:].lower()
    return tuple(
        command
        for command in SLASH_COMMANDS
        if command.name.startswith(prefix)
        and (include_effort or command.name != "effort")
    )



def find_mode(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> Optional[ModeOption]:
    needle = value.strip().lower()
    matches = [mode for mode in modes if needle in {mode.id.lower(), mode.label.lower()}]
    return matches[0] if len(matches) == 1 else None


def mode_matches(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> tuple[ModeOption, ...]:
    needle = value.strip().lower()
    return tuple(mode for mode in modes if not needle or needle in mode.id.lower() or needle in mode.label.lower())
