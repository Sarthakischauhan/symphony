"""One shape for "something about an extension needs the user's attention"."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Diagnostic:
    """A problem (``error``) or a fact worth knowing (``notice``), tied to a path or name.

    Extension problems are reported, never raised: one bad skill or plugin must not
    stop the agent from starting.
    """

    source: str
    message: str
    level: Literal["error", "notice"] = "error"

    def render(self) -> str:
        return f"{self.source}: {self.message}"


__all__ = ["Diagnostic"]
