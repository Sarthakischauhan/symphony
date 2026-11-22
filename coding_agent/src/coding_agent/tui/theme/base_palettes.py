"""The palettes a plugin theme falls back to for every slot it leaves unset.

Claude themes name a ``base`` (``dark``, ``light`` and their ``-ansi`` and
``-daltonized`` variants). Symphony has one dark palette (the packaged theme.toml);
the light and ANSI palettes are defined here with the same keys.

The ANSI palettes hold terminal colors only (Rich names), so the terminal's own
palette decides how they look. Syntax colors of an ANSI theme come from here too.
"""

from __future__ import annotations

from functools import cache
from typing import Mapping

from coding_agent.tui.theme.load import load_theme, packaged_theme_path

ANSI_BASES = frozenset({"dark-ansi", "light-ansi"})

_LIGHT = {
    "background": "#FAFAFA",
    "foreground": "#1F2328",
    "accent": "#7C3AED",
    "muted": "#6B7280",
    "muted_dim": "#8A929C",
    "edge": "#D4D8DD",
    "comment": "#8A929C",
    "keyword": "#CF222E",
    "type_keywords": "#CF222E",
    "string": "#1A7F37",
    "function": "#8250DF",
    "variable": "#1F2328",
    "number": "#B35900",
    "operator": "#6E7781",
    "punctuation": "#57606A",
    "type": "#953800",
    "tag": "#116329",
    "attribute": "#0550AE",
    "constant": "#0550AE",
    "surface": "#F0F2F4",
    "overlay": "#E1E4E8",
    "subtext": "#57606A",
    "panel_edge_focus": "#8C959F",
    "diff_added": "#DAFBE1",
    "diff_removed": "#FFEBE9",
}

_DARK_ANSI = {
    "background": "default",
    "foreground": "default",
    "accent": "bright_magenta",
    "muted": "bright_black",
    "muted_dim": "bright_black",
    "edge": "bright_black",
    "comment": "bright_black",
    "keyword": "red",
    "type_keywords": "red",
    "string": "green",
    "function": "blue",
    "variable": "default",
    "number": "yellow",
    "operator": "cyan",
    "punctuation": "bright_black",
    "type": "bright_yellow",
    "tag": "cyan",
    "attribute": "bright_blue",
    "constant": "bright_yellow",
    "surface": "black",
    "overlay": "bright_black",
    "subtext": "white",
    "panel_edge_focus": "bright_black",
    "diff_added": "default",
    "diff_removed": "default",
}

_LIGHT_ANSI = {
    **_DARK_ANSI,
    "accent": "magenta",
    "muted": "bright_black",
    "surface": "white",
    "overlay": "bright_white",
    "subtext": "black",
    "type": "yellow",
    "constant": "yellow",
    "attribute": "blue",
}


@cache
def _dark() -> dict[str, str]:
    return dict(load_theme(packaged_theme_path()).colors)


def base_palette(base: str) -> dict[str, str]:
    """A copy of the palette for a Claude ``base``; daltonized variants use the plain dark or light one."""
    table: Mapping[str, str]
    if base.startswith("light"):
        table = _LIGHT_ANSI if base in ANSI_BASES else _LIGHT
    else:
        table = _DARK_ANSI if base in ANSI_BASES else _dark()
    return dict(table)


__all__ = ["ANSI_BASES", "base_palette"]
