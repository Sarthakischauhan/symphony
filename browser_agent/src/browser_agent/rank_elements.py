"""Order page elements by how well their names match the goal."""

from __future__ import annotations

import re

from browser_agent.models import Element

# Function words only. Task words such as "book" or "search" often name the control itself.
_STOPWORDS = frozenset("the and for with from that this into onto your page then when stop once visible report".split())


def goal_tokens(goal: str, min_length: int = 3) -> list[str]:
    """Distinctive goal words in order: lowercase, at least ``min_length`` long, no stopwords."""
    words = re.findall(rf"[a-z0-9]{{{min_length},}}", goal.lower())
    return [word for word in dict.fromkeys(words) if word not in _STOPWORDS]


def rank_by_goal(elements: list[Element], goal: str) -> list[Element]:
    """Elements with the most goal words in their name first; ties keep page order."""
    tokens = goal_tokens(goal)
    return sorted(elements, key=lambda element: -sum(token in element.name.lower() for token in tokens))


__all__ = ["goal_tokens", "rank_by_goal"]
