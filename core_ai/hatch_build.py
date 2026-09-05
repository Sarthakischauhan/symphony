"""Hatch build hook for symphony-core.

The model catalog in ``src/core_ai/models/generated.py`` is a checked-in
snapshot and ships as-is. Building or installing the package never touches
the network and never rewrites the snapshot.

Maintainers refresh the snapshot explicitly, either by running
``uv run python scripts/generate_models.py`` and committing the result, or by
setting ``CORE_AI_REFRESH_CATALOG=1`` for a single build. In that opt-in mode
a failed refresh fails the build instead of silently keeping stale data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

REFRESH_ENV = "CORE_AI_REFRESH_CATALOG"


def refresh_requested(environ: "os._Environ[str] | dict[str, str]" = os.environ) -> bool:
    return environ.get(REFRESH_ENV, "").strip().lower() in {"1", "true", "yes"}


def refresh_catalog(root: Path) -> Path:
    """Regenerate the snapshot from models.dev. Raises on any failure."""
    try:
        import httpx  # noqa: F401  # only needed for the opt-in refresh
    except ImportError as exc:
        raise RuntimeError(
            f"{REFRESH_ENV} needs httpx in the build environment; run "
            "`uv run python scripts/generate_models.py` instead, or build with "
            "`--no-build-isolation` in an environment that has httpx."
        ) from exc
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from generate_models import generate
    finally:
        sys.path.remove(str(scripts))
    return generate(strict=True)


class CustomBuildHook(BuildHookInterface):
    """Ship the checked-in catalog; refresh only when explicitly asked."""

    def initialize(self, version: str, build_data: dict) -> None:
        if not refresh_requested():
            return
        self.app.display_info(f"{REFRESH_ENV} set: refreshing model catalog from models.dev")
        refresh_catalog(Path(self.root))
