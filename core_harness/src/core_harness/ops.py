"""Operations a client sends into a run.

Events go out through ``EventSink``. Operations come in through
``CoreHarness.submit``. Every host (TUI, stdio, server) sends the same
three, so none of them has to reach into the run task or a sink's futures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from core_ai.types import Content


@dataclass(frozen=True)
class Interrupt:
    """Stop the active run. ``reason`` is reported on ``run_cancelled``."""

    reason: str = "cancelled"


@dataclass(frozen=True)
class Answer:
    """Reply to the question a run asked with this ``request_id``."""

    request_id: str
    value: str = ""


@dataclass(frozen=True)
class UserInput:
    """A user message for the active run, read at its next turn."""

    content: Content


Op = Union[Interrupt, Answer, UserInput]

__all__ = ["Answer", "Interrupt", "Op", "UserInput"]
