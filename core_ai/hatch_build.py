from __future__ import annotations

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Regenerate the shipped model catalog while packaging core_ai."""

    def initialize(self, version: str, build_data: dict) -> None:
        scripts = Path(self.root) / "scripts"
        sys.path.insert(0, str(scripts))
        from generate_models import generate

        generate(strict=False)
