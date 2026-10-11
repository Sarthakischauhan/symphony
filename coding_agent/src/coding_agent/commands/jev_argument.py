"""Read the ``/jev`` argument once for every surface.

The TUI keeps a rule for the current session and the stdio protocol writes it
to config. Where the rule is stored stays with each surface; this module only
decides what the argument means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_TOGGLE = frozenset({"", "toggle"})
_ON = frozenset({"on", "enable", "true", "1"})
_OFF = frozenset({"off", "disable", "false", "0"})


@dataclass(frozen=True)
class JevChange:
    """Result of ``/jev <argument>``. ``rule`` is None when the rule is unchanged."""

    enabled: bool
    rule: Optional[str] = None


def parse_jev_argument(current: bool, argument: str) -> JevChange:
    """Resolve ``/jev [toggle|on|off|<rule>]``.

    Keywords are case-insensitive. Any other text is a rule (kept as typed,
    minus surrounding whitespace) and turns Jev on.
    """
    text = argument.strip()
    needle = text.lower()
    if needle in _TOGGLE:
        return JevChange(enabled=not current)
    if needle in _ON:
        return JevChange(enabled=True)
    if needle in _OFF:
        return JevChange(enabled=False)
    return JevChange(enabled=True, rule=text)
