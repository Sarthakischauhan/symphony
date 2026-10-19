"""One process owns one session; reuse the existing stdio interaction protocol."""

import asyncio
import json
import sys
from pathlib import Path

from coding_agent.addons.persistence import register_active, release_active
from coding_agent.protocols import stdio


def models(workspace, model):
    """Print the stdio model catalog; provider credentials stay in this process."""
    from core_ai import build_default_registry, default_model_id

    from coding_agent.config import ensure_spawn_settings

    stdio.load_provider_env(workspace)
    registry = build_default_registry()
    catalog = stdio.model_catalog(registry, "web")
    # Match what a new session would pick: --model, then the last used model.
    last = ensure_spawn_settings(workspace).last_model
    catalog["default"] = default_model_id(registry, model or last)
    sys.__stdout__.write(json.dumps(catalog, default=str) + "\n")
    return 0


def main():
    if sys.argv[1] == "--models":
        return models(Path(sys.argv[2]), sys.argv[3] or None)
    workspace, session_id, model = sys.argv[1:]
    try:
        register_active(session_id, workspace=workspace, kind="web")
        sys.stdout = sys.stderr
        return asyncio.run(stdio.serve(Path(workspace), model or None, session_id, client="tui"))
    finally:
        release_active()


if __name__ == "__main__":
    raise SystemExit(main())
