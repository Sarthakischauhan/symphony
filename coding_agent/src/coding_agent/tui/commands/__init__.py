"""Slash-command definitions and lookup helpers."""

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


MODEL_CATALOG = (
    ModelOption("openai:gpt-5.6-luna", "GPT-5.6 Luna", "Thinking model"),
    ModelOption("openai:gpt-4o-mini", "GPT-4o mini", "Fast and economical"),
    ModelOption("openai:gpt-4.1-mini", "GPT-4.1 mini", "Fast coding model"),
    ModelOption("openai:gpt-4.1", "GPT-4.1", "Most capable OpenAI model in this catalog"),
    ModelOption("anthropic:claude-sonnet-5", "Claude Sonnet 5", "Fast Anthropic coding model"),
    ModelOption("anthropic:claude-opus-5", "Claude Opus 5", "Most capable Anthropic model"),
    ModelOption("anthropic:claude-fable-5", "Claude Fable 5", "Anthropic reasoning model"),
    ModelOption("gemini:gemini-3.7-flash", "Gemini 3.7 Flash", "Fast Gemini coding model"),
    ModelOption("gemini:gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Most capable Gemini model"),
)

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


def find_model(value: str, models: Iterable[ModelOption] = MODEL_CATALOG) -> Optional[ModelOption]:
    needle = value.strip().lower()
    if not needle:
        return None
    matches = [
        model for model in models
        if needle in {model.id.lower(), model.id.split(":", 1)[-1].lower(), model.label.lower()}
    ]
    return matches[0] if len(matches) == 1 else None


def model_matches(value: str, models: Iterable[ModelOption] = MODEL_CATALOG) -> tuple[ModelOption, ...]:
    needle = value.strip().lower()
    return tuple(model for model in models if not needle or needle in model.id.lower() or needle in model.label.lower())


def find_mode(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> Optional[ModeOption]:
    needle = value.strip().lower()
    matches = [mode for mode in modes if needle in {mode.id.lower(), mode.label.lower()}]
    return matches[0] if len(matches) == 1 else None


def mode_matches(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> tuple[ModeOption, ...]:
    needle = value.strip().lower()
    return tuple(mode for mode in modes if not needle or needle in mode.id.lower() or needle in mode.label.lower())
