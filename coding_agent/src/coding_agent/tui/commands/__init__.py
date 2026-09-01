"""Slash-command catalogs and handlers for the coding-agent TUI."""

from coding_agent.tui.commands.catalog import (
    EFFORT_CATALOG,
    EFFORTS,
    MODE_CATALOG,
    SLASH_COMMANDS,
    EffortOption,
    ModeOption,
    ModelOption,
    PlanOption,
    SlashCommand,
    command_matches,
    find_mode,
    find_model,
    mode_matches,
    model_matches,
    model_options,
)
from coding_agent.tui.commands.manager import (
    CommandManager,
    effort_matches,
    effort_options_for_model,
    model_supports_effort,
    toggle_mode,
)

__all__ = [
    "CommandManager",
    "EFFORT_CATALOG",
    "MODE_CATALOG",
    "EFFORTS",
    "EffortOption",
    "ModeOption",
    "model_options",
    "ModelOption",
    "PlanOption",
    "SLASH_COMMANDS",
    "SlashCommand",
    "command_matches",
    "effort_matches",
    "effort_options_for_model",
    "find_mode",
    "find_model",
    "mode_matches",
    "model_matches",
    "model_supports_effort",
    "toggle_mode",
]
