"""Construction helpers for the TUI's coding agent."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from coding_agent.agent import CodingAgent
from coding_agent.tui.control_plane import TextualControlPlane


def build_agent(
    *,
    workspace: Path,
    control_plane: TextualControlPlane,
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: bool = True,
) -> CodingAgent:
    """Build a coding agent from whatever provider credentials are available."""
    from core_ai import build_default_registry, default_model_id

    registry = build_default_registry()
    return CodingAgent(
        registry=registry,
        model_id=default_model_id(registry, model_id),
        workspace=workspace,
        control_plane=control_plane,
        session_id=session_id,
        enable_learning=enable_learning,
    )
