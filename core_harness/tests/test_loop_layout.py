"""Layout and import-ban checks for the split harness loop."""

from __future__ import annotations

import ast
from pathlib import Path

import core_harness
from core_harness.loop import run_session


def _harness_src() -> Path:
    return Path(core_harness.__file__).resolve().parent


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_loop_is_a_package_with_session_stream_tools() -> None:
    root = _harness_src() / "loop"
    assert (root / "__init__.py").is_file()
    assert (root / "session.py").is_file()
    assert (root / "stream.py").is_file()
    assert (root / "tools.py").is_file()
    assert not (root.parent / "loop.py").exists()
    assert callable(run_session)
    former_monolith_loc = 774
    for name in ("session.py", "stream.py", "tools.py"):
        loc = len((root / name).read_text(encoding="utf-8").splitlines())
        assert loc < former_monolith_loc, f"{name} is {loc} lines"


def test_core_harness_does_not_import_learning() -> None:
    offenders: list[str] = []
    for path in _harness_src().rglob("*.py"):
        for module in _imported_modules(path):
            if module == "coding_agent" or module.startswith("coding_agent."):
                offenders.append(f"{path.name}: {module}")
            if "learning" in module.split("."):
                offenders.append(f"{path.name}: {module}")
    assert offenders == []
