"""The per-session figures the top bar and footer show."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

ArtifactEntry = tuple[str, str, Path]


def artifact_key(path: Path) -> Path:
    """The artifact's own folder, so every version of it counts once.

    Stored paths are ``artifacts/<id>/v<version>/<entry>``, possibly nested.
    """
    version_dir = next(
        (
            parent
            for parent in path.parents
            if parent.name.startswith("v")
            and parent.name[1:].isdigit()
            and parent.parent.parent.name == "artifacts"
        ),
        None,
    )
    return version_dir.parent if version_dir is not None else path


@dataclass(frozen=True)
class SessionChrome:
    """Context usage, spend and artifacts for one session.

    ``/new`` passes a fresh one (only the model's context limit); resume passes
    what the stored session holds. ``reset_session_chrome`` applies it to the
    top bar and footer in one step, so the two cannot show different sessions.
    """

    context_limit: Optional[int] = None
    tokens_used: int = 0
    costs: Mapping[str, float] = field(default_factory=dict)
    artifacts: Mapping[Path, ArtifactEntry] = field(default_factory=dict)
