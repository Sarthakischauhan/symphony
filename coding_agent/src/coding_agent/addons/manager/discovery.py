"""Where user addons live and which names they may not take.

Only ``<symphony home>/addons/<name>/`` is scanned (``SYMPHONY_HOME``
overrides the home). There is no project-local addon folder.
"""

from __future__ import annotations

import pkgutil
from pathlib import Path
from typing import Collection

import coding_agent.addons as builtin_addons
from core_harness.extensions import ExtensionSnapshot, load_addons

from coding_agent.config import symphony_dir

BUILTIN_ADDON_NAMES: frozenset[str] = frozenset(
    module.name for module in pkgutil.iter_modules(builtin_addons.__path__)
)


def user_addons_root() -> Path:
    return symphony_dir() / "addons"


def load_user_addons(reserved_names: Collection[str] = ()) -> ExtensionSnapshot:
    return load_addons(
        (user_addons_root(),),
        reserved_names=BUILTIN_ADDON_NAMES | frozenset(reserved_names),
    )


__all__ = ["BUILTIN_ADDON_NAMES", "load_user_addons", "user_addons_root"]
