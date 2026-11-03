"""Which Claude theme slots feed which Symphony ``[colors]`` token.

Each row names a Symphony token and the Claude slots that can supply it, best first;
the first slot the theme sets to a valid color wins. A token no slot supplies keeps
the base palette's value. Claude slot names come from claude-themes'
``schemas/theme.schema.json``.

``background`` is deliberately not a source. In Claude it is a foreground accent for
background tasks (the schema says "Not a fill colour"), and themes set it to a cyan
or blue: mapping it would paint the whole screen that color. Claude never paints a
terminal background, so the one slot that carries the theme's real canvas color,
``clawd_background`` (the mascot's backdrop), supplies Symphony's ``background``.
Every theme in the marketplace sets it equal to its palette background.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotMapping:
    """A Symphony ``[colors]`` token and the Claude slots that can supply it, in order of preference."""

    token: str
    slots: tuple[str, ...]


# Chrome: what the top bar, composer, footer and panels read.
UI_MAPPINGS = (
    SlotMapping("foreground", ("text",)),
    SlotMapping("muted", ("subtle",)),
    SlotMapping("muted_dim", ("inactive",)),
    SlotMapping("edge", ("promptBorder",)),
    SlotMapping("accent", ("claude",)),
    SlotMapping("string", ("success",)),
    SlotMapping("keyword", ("error",)),
    SlotMapping("type_keywords", ("error",)),
    SlotMapping("number", ("warning",)),
    SlotMapping("diff_added", ("diffAdded",)),
    SlotMapping("diff_removed", ("diffRemoved",)),
    SlotMapping("overlay", ("selectionBg",)),
    SlotMapping("surface", ("userMessageBackground",)),
    SlotMapping("background", ("clawd_background",)),
)

# Syntax colors of a regular (non-ANSI) theme, derived from the theme's own palette.
# Claude has no syntax slots, so these borrow its hue slots: the eight colors it
# gives subagents, then its rainbow, then the base palette.
SYNTAX_MAPPINGS = (
    SlotMapping("variable", ("text",)),
    SlotMapping("comment", ("subtle",)),
    SlotMapping("punctuation", ("subtle",)),
    SlotMapping("function", ("blue_FOR_SUBAGENTS_ONLY", "rainbow_blue")),
    SlotMapping("type", ("yellow_FOR_SUBAGENTS_ONLY", "rainbow_yellow")),
    SlotMapping("tag", ("cyan_FOR_SUBAGENTS_ONLY",)),
    SlotMapping("attribute", ("purple_FOR_SUBAGENTS_ONLY", "rainbow_indigo")),
    SlotMapping("constant", ("orange_FOR_SUBAGENTS_ONLY", "rainbow_orange")),
    SlotMapping("operator", ("pink_FOR_SUBAGENTS_ONLY", "rainbow_violet")),
)

# Tokens the terminal owns in an ANSI theme: Claude does not paint a background there.
TERMINAL_OWNED_TOKENS = frozenset({"background"})

__all__ = ["SYNTAX_MAPPINGS", "TERMINAL_OWNED_TOKENS", "UI_MAPPINGS", "SlotMapping"]
