"""Construction helpers for the TUI's coding agent."""

from __future__ import annotations

import os
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
    """Build an OpenAI-backed coding agent from the current environment."""
    from core_ai import ModelRegistry
    from core_ai.providers.openai import OpenAIProvider

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = model_id or os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    if ":" not in model_name:
        model_name = f"openai:{model_name}"

    registry = ModelRegistry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))
    return CodingAgent(
        registry=registry,
        model_id=model_name,
        workspace=workspace,
        control_plane=control_plane,
        session_id=session_id,
        enable_learning=enable_learning,
    )
