"""The TUI reads declared attributes. ``getattr`` and ``hasattr`` probes stay out.

A probe hides a missing or misspelled attribute behind a default, so a typo or a
removed field turns into silent wrong behavior. Declare the attribute, inject
the dependency, or narrow with ``isinstance`` instead.

If a probe truly cannot be typed, add it to ``ALLOWED`` as
``("relative/path.py", "enclosing_function"): "why it cannot be typed"``.
Keep that table as short as possible. It is empty today.
"""

from __future__ import annotations

import ast
from pathlib import Path

import coding_agent.tui

TUI_ROOT = Path(coding_agent.tui.__file__).parent
PROBES = frozenset({"getattr", "hasattr"})

# (path relative to coding_agent/tui, enclosing function or "<module>") -> reason.
ALLOWED: dict[tuple[str, str], str] = {}


def _probe_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name) and func.id in PROBES:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in PROBES:
        return func.attr
    return None


def find_probes(
    source: str, relative: str, allowed: dict[tuple[str, str], str] = ALLOWED
) -> list[tuple[str, int, str]]:
    """Return ``(path, line, function)`` for each getattr/hasattr call not in ``allowed``."""
    found: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Call) and _probe_name(child) and (relative, scope) not in allowed:
                found.append((relative, child.lineno, scope))
            visit(child, inner)

    visit(ast.parse(source), "<module>")
    return found


def test_tui_has_no_getattr_or_hasattr() -> None:
    offenders: list[str] = []
    for path in sorted(TUI_ROOT.rglob("*.py")):
        relative = path.relative_to(TUI_ROOT).as_posix()
        for where, line, scope in find_probes(path.read_text(encoding="utf-8"), relative):
            offenders.append(f"{where}:{line} in {scope}")
    assert not offenders, "getattr/hasattr under coding_agent/tui:\n" + "\n".join(offenders)


def test_allowlist_entries_name_a_reason_and_a_real_probe() -> None:
    for (relative, scope), reason in ALLOWED.items():
        assert reason.strip(), f"{relative}:{scope} needs a reason"
        source = (TUI_ROOT / relative).read_text(encoding="utf-8")
        assert any(where == scope for _, _, where in find_probes(source, relative, {})), (
            f"stale allowlist entry: {relative}:{scope}"
        )


def test_checker_flags_probes_in_functions_and_modules() -> None:
    source = (
        "x = getattr(obj, 'a', None)\n"
        "class C:\n"
        "    async def m(self):\n"
        "        if hasattr(self, 'b'):\n"
        "            return builtins.getattr(self, 'c')\n"
    )
    assert find_probes(source, "demo.py") == [
        ("demo.py", 1, "<module>"),
        ("demo.py", 4, "m"),
        ("demo.py", 5, "m"),
    ]
    assert find_probes(source, "demo.py", {("demo.py", "m"): "tolerated"}) == [("demo.py", 1, "<module>")]
    assert find_probes("value = obj.getattr_like\nsetattr(obj, 'a', 1)\n", "demo.py") == []
