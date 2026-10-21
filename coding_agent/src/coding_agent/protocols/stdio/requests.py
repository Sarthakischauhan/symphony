"""Typed request frames for hosts that browse sessions and switch models live.

Every request carries a ``request_id`` and gets exactly one reply frame with the
same id (or an ``error`` frame with that id). The replies come from the session
store and model registry the live agent already owns, so hosts never read
Symphony's files themselves.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from coding_agent.addons.persistence import JsonlPersistence, active_session_ids
from coding_agent.config import ensure_spawn_settings
from coding_agent.protocols.stdio.transport import CAPABILITIES, PROTOCOL_VERSION

if TYPE_CHECKING:
    from coding_agent.agent import CodingAgent

Frame = dict[str, object]


def model_id(agent: CodingAgent) -> str:
    """The model the live harness runs with."""
    return agent.harness.model_id


def git_branch(workspace: Path) -> str:
    """Current branch name; empty outside a repository or on a detached HEAD."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=workspace,
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def ready_frame(agent: CodingAgent, workspace: Path, client: str) -> Frame:
    return {
        "type": "ready",
        "session_id": agent.session_id,
        "model": model_id(agent),
        "workspace": str(workspace),
        "branch": git_branch(workspace),
        "client": client,
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": CAPABILITIES,
    }


def _store(agent: CodingAgent) -> JsonlPersistence:
    store = agent.persistence
    if not isinstance(store, JsonlPersistence):
        raise ValueError("this session store does not support browsing sessions")
    return store


async def session_list(agent: CodingAgent, request_id: str) -> Frame:
    """Parent sessions of this client's store, newest first."""
    store = _store(agent)
    active = active_session_ids()
    return {
        "type": "sessions",
        "request_id": request_id,
        "sessions": [
            {**asdict(item), "active": item.session_id in active}
            for item in await store.list_sessions()
            if item.client == store.client
        ],
    }


async def session_history(agent: CodingAgent, request_id: str, session_id: str) -> Frame:
    """Transcript, journal events, and subagent children of one session."""
    store = _store(agent)
    store.session_dir(session_id)  # Validates the id before any read.
    transcript = await store.load_transcript(session_id=session_id)
    return {
        "type": "session_history",
        "request_id": request_id,
        "session_id": session_id,
        "messages": [message.model_dump(mode="json") for message in transcript],
        "events": [[kind, payload] for kind, payload in await store.load_events(session_id=session_id)],
        "children": await store.load_children(parent_session_id=session_id),
    }


def select_model(agent: CodingAgent, request_id: str, selected: str) -> Frame:
    """Switch the live harness to ``selected``, as the TUI model picker does."""
    namespaces = agent.registry.namespaces()
    known = {item.full_id: item for item in agent.registry.models() if item.provider in namespaces}
    info = known.get(selected)
    if info is None:
        raise ValueError(f"unknown model: {selected}")
    agent.harness.model_id = info.full_id
    if agent.learning_loop is not None:
        agent.learning_loop.model_id = info.full_id
    agent.config = ensure_spawn_settings(agent.workspace, config=agent.config, overrides={"last_model": info.full_id})
    return {
        "type": "model_selected",
        "request_id": request_id,
        "model": info.full_id,
        "context_limit": info.context_limit,
    }


__all__ = ["git_branch", "model_id", "ready_frame", "select_model", "session_history", "session_list"]
