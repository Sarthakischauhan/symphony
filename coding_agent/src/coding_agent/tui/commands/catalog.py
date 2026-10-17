"""Moved to :mod:`coding_agent.commands.catalog`; this path re-exports it for one release."""

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

__all__ = [
    "EFFORT_CATALOG",
    "EFFORTS",
    "SLASH_COMMANDS",
    "EffortOption",
    "ModelOption",
    "PersonalityOption",
    "SlashCommand",
    "command_matches",
    "find_model",
    "find_personality",
    "model_matches",
    "model_options",
    "personality_matches",
    "personality_options",
]
