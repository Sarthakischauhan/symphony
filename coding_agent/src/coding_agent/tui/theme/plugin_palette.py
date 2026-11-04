"""Turn a plugin's theme into a complete Symphony palette.

A Claude theme starts from the palette of its ``base`` and overlays each mapped slot
(``claude_slots``). A Symphony ``theme.toml`` theme overlays its ``[colors]``. Slots
and keys that are missing or not valid colors are skipped, so a partial theme still
gives a full palette.

A theme whose base is ANSI keeps the terminal in charge: its syntax colors stay the
ANSI palette's, and it never sets a background. Regular themes derive syntax colors
from their own palette.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from coding_agent.addons.plugins import PluginTheme
from coding_agent.tui.theme.ansi_colors import parse_theme_color
from coding_agent.tui.theme.base_palettes import ANSI_BASES, base_palette
from coding_agent.tui.theme.claude_slots import SYNTAX_MAPPINGS, TERMINAL_OWNED_TOKENS, UI_MAPPINGS, SlotMapping
from coding_agent.tui.theme.load import OPTIONAL_COLOR_KEYS, SYMPHONY_COLOR_KEYS

KNOWN_TOKENS = frozenset((*SYMPHONY_COLOR_KEYS, *OPTIONAL_COLOR_KEYS))


@dataclass(frozen=True)
class ThemePalette:
    """A theme ready to publish: complete ``[colors]`` and whether the terminal's palette is in use."""

    name: str
    colors: dict[str, str]
    ansi: bool


def palette_for(theme: PluginTheme) -> ThemePalette:
    ansi = theme.base in ANSI_BASES
    colors = base_palette(theme.base)
    if theme.format == "claude":
        colors.update(_claude_colors(theme.colors, ansi))
    else:
        colors.update(_native_colors(theme.colors))
    return ThemePalette(theme.qualified_name, colors, ansi)


def _claude_colors(slots: Mapping[str, str], ansi: bool) -> dict[str, str]:
    mappings: tuple[SlotMapping, ...] = UI_MAPPINGS if ansi else UI_MAPPINGS + SYNTAX_MAPPINGS
    resolved: dict[str, str] = {}
    for mapping in mappings:
        if ansi and mapping.token in TERMINAL_OWNED_TOKENS:
            continue
        for slot in mapping.slots:
            color = parse_theme_color(slots[slot]) if slot in slots else None
            if color is not None:
                resolved[mapping.token] = color
                break
    return resolved


def _native_colors(colors: Mapping[str, str]) -> dict[str, str]:
    parsed = {token: parse_theme_color(value) for token, value in colors.items() if token in KNOWN_TOKENS}
    return {token: color for token, color in parsed.items() if color is not None}


__all__ = ["ThemePalette", "palette_for"]
