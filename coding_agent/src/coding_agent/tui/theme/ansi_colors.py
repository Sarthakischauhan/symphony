"""Theme color values: parse Claude's color syntax, and hand colors to Textual.

A theme color is stored as one string that Rich accepts, because palette values land
in Rich styles (``"bold " + color``): ``#rrggbb``, a Rich ANSI name such as
``bright_black``, or ``color(n)`` for the 256-color palette. Textual CSS cannot read
``color(n)`` or Rich's bare names as terminal colors, so ``textual_color`` converts at
the one place a palette becomes CSS.
"""

from __future__ import annotations

import re

from rich.color import Color as RichColor
from rich.color import ColorParseError
from textual.color import Color as TextualColor

ANSI_NAMES = frozenset({"black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"})
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$")
_ANSI = re.compile(r"^ansi:([a-z]+?)(Bright)?$")
_ANSI_256 = re.compile(r"^ansi256\(\s*(\d{1,3})\s*\)$")


def parse_theme_color(value: str) -> str | None:
    """Rich-compatible color for a Claude color value, or None when it is not a valid color.

    Accepts ``#rgb``, ``#rrggbb``, ``rgb(r,g,b)``, ``ansi:<name>`` / ``ansi:<name>Bright``
    and ``ansi256(n)``. Claude ignores invalid values at runtime, so callers drop None.
    """
    text = value.strip()
    if _HEX.match(text):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        return "#" + digits.lower()
    if rgb := _RGB.match(text):
        channels = [int(part) for part in rgb.groups()]
        if max(channels) > 255:
            return None
        return "#{:02x}{:02x}{:02x}".format(*channels)
    if named := _ANSI.match(text):
        name, bright = named.groups()
        if name not in ANSI_NAMES:
            return None
        return f"bright_{name}" if bright else name
    if indexed := _ANSI_256.match(text):
        number = int(indexed.group(1))
        return f"color({number})" if number <= 255 else None
    return None


def textual_color(value: str) -> str:
    """CSS color for a palette value. ANSI 0-15 and ``default`` stay terminal colors; 16-255 become their RGB."""
    if value.startswith("#"):
        return value
    try:
        return TextualColor.from_rich_color(RichColor.parse(value)).css
    except ColorParseError as exc:
        raise ValueError(f"{value!r} is not a color") from exc


__all__ = ["parse_theme_color", "textual_color"]
