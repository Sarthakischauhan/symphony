"""Slash-command catalogs and handlers for the coding-agent TUI."""

from coding_agent.commands.catalog import (
    EFFORT_CATALOG,
    EFFORTS,
    SLASH_COMMANDS,
    EffortOption,
    ModelOption,
    PersonalityOption,
    SlashCommand,
    command_matches,
    find_model,
    find_personality,
    model_matches,
    model_options,
    personality_matches,
    personality_options,
)
from coding_agent.tui.commands.manager import (
    CommandManager,
    effort_matches,
    effort_options_for_model,
    model_supports_effort,
)

__all__ = [
    "CommandManager",
    "EFFORT_CATALOG",
    "EFFORTS",
    "EffortOption",
    "model_options",
    "ModelOption",
    "PersonalityOption",
    "SLASH_COMMANDS",
    "SlashCommand",
    "command_matches",
    "effort_matches",
    "effort_options_for_model",
    "find_model",
    "find_personality",
    "model_matches",
    "model_supports_effort",
    "personality_matches",
    "personality_options",
]
