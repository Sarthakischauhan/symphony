"""Defer an attribute until the module that owns it has finished importing."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def resolve(module_globals: dict[str, Any], name: str, exports: dict[str, tuple[str, str]]) -> Any:
    target = exports.get(name)
    if target is None:
        module_name = module_globals.get("__name__", "module")
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    source, attr = target
    value = getattr(import_module(source), attr)
    module_globals[name] = value
    return value
