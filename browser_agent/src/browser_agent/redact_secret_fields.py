"""Decide which fields hold secrets, so their values stay out of events and traces.

The check is not name-only. A password input with a generic placeholder such
as "Enter code" has no telling name, so the page's own signal (``type=password``
or a credential ``autocomplete`` token, carried as ``Element.secret``) comes
first. The name pattern only catches secret fields the page did not mark.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from browser_agent.models import Element

SECRET_MARKER = "***"
_SECRET_NAME = re.compile(r"password|passcode|secret|\botp\b|\bpin\b|cvv|card", re.IGNORECASE)


def is_secret_field(element: Optional[Element]) -> bool:
    """True when the page marked the field secret or its name says it is."""
    return element is not None and (element.secret or bool(_SECRET_NAME.search(element.name)))


def redact_typed(element: Optional[Element], text: str) -> str:
    """``***`` in place of text typed into a secret field; other text unchanged."""
    return SECRET_MARKER if text and is_secret_field(element) else text


__all__ = ["SECRET_MARKER", "is_secret_field", "redact_typed"]
