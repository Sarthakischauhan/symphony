"""Semantic layer over AST summaries: symbols, inheritance, call graph.

Call relationships are best-effort name-based resolutions (not type-checked).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from coding_agent.ast.models import (
    CodebaseSummary,
    ConstantSummary,
    FunctionSummary,
    ModuleSummary,
)


@dataclass(frozen=True)
class Symbol:
    """A named definition in the codebase."""

    qualified_name: str
    kind: str  # class | function | method | constant | nested_function
    name: str
    path: str
    lineno: int
    signature: str | None = None
    docstring: str | None = None


@dataclass
class SemanticIndex:
    """Queryable semantic view of a codebase summary."""

    root: str
    symbols: dict[str, Symbol] = field(default_factory=dict)
    by_name: dict[str, list[str]] = field(default_factory=dict)
    inheritance: dict[str, tuple[str, ...]] = field(default_factory=dict)
    callers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    callees: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    imports: dict[str, tuple[str, ...]] = field(default_factory=dict)
    aliases: dict[str, dict[str, str]] = field(default_factory=dict)

    def find_symbol(self, name: str, *, limit: int = 20) -> list[Symbol]:
        needle = name.strip()
        if not needle:
            return []

        exact = [self.symbols[q] for q in self.by_name.get(needle, []) if q in self.symbols]
        if exact:
            return exact[:limit]

        lowered = needle.lower()
        matches = [
            symbol
            for qn, symbol in self.symbols.items()
            if lowered in qn.lower() or lowered in symbol.name.lower()
        ]
        return matches[:limit]

    def get_callers(self, name: str) -> list[str]:
        keys = self._resolve_keys(name)
        found: set[str] = set()
        for key in keys:
            found.update(self.callers.get(key, set()))
        return sorted(found)

    def get_callees(self, name: str) -> list[str]:
        keys = self._resolve_keys(name)
        found: set[str] = set()
        for key in keys:
            found.update(self.callees.get(key, set()))
        return sorted(found)

    def get_inheritance(self, name: str) -> dict[str, list[str]]:
        keys = self._resolve_keys(name)
        bases: list[str] = []
        subclasses: list[str] = []
        short = name.split(".")[-1].split(":")[-1]
        for key in keys:
            bases.extend(self.inheritance.get(key, ()))
        for qn, parent_bases in self.inheritance.items():
            if short in parent_bases or any(short == b.split(".")[-1] for b in parent_bases):
                if qn not in keys:
                    subclasses.append(qn)
        return {"bases": sorted(set(bases)), "subclasses": sorted(set(subclasses))}

    def module_outline(self, path: str) -> str | None:
        symbols = [s for s in self.symbols.values() if s.path == path]
        if not symbols:
            return None
        lines = [f"Module {path}:"]
        for symbol in sorted(symbols, key=lambda s: (s.lineno, s.name)):
            sig = symbol.signature or ""
            lines.append(f"- {symbol.kind} {symbol.name}{sig} [line {symbol.lineno}]")
        return "\n".join(lines)

    def to_markdown(self, *, max_symbols: int = 24, max_edges: int = 12) -> str:
        if not self.symbols:
            return ""

        lines = [
            "Semantic index (best-effort):",
            f"- Symbols: {len(self.symbols)}",
            f"- Inheritance edges: {len(self.inheritance)}",
            f"- Call-graph functions: {len(self.callees)}",
            "- Name-based call edges may be ambiguous across duplicates/imports.",
        ]

        inheritance_lines = []
        for qn, bases in sorted(self.inheritance.items()):
            if bases:
                inheritance_lines.append(f"- {qn} -> {', '.join(bases)}")
        if inheritance_lines:
            lines.append("")
            lines.append("Inheritance:")
            lines.extend(inheritance_lines[:max_edges])

        call_lines = []
        for caller, callees in sorted(self.callees.items(), key=lambda item: -len(item[1])):
            if not callees:
                continue
            shown = ", ".join(sorted(callees)[:6])
            call_lines.append(f"- {caller} calls {shown}")
            if len(call_lines) >= max_edges:
                break
        if call_lines:
            lines.append("")
            lines.append("Call graph sample (best-effort):")
            lines.extend(call_lines)

        lines.append("")
        lines.append("Symbol directory:")
        for symbol in sorted(self.symbols.values(), key=lambda s: s.qualified_name)[:max_symbols]:
            lines.append(f"- {symbol.kind}: {symbol.qualified_name}")
        if len(self.symbols) > max_symbols:
            lines.append(f"- … {len(self.symbols) - max_symbols} more (use ast_query)")

        return "\n".join(lines)

    def _resolve_keys(self, name: str) -> list[str]:
        if name in self.symbols:
            return [name]
        if name in self.by_name:
            return list(self.by_name[name])
        matches = [qn for qn in self.symbols if qn.endswith(":" + name) or qn.endswith("." + name)]
        return matches


def build_semantic_index(summary: CodebaseSummary) -> SemanticIndex:
    """Build a semantic index from a codebase summary."""
    index = SemanticIndex(root=summary.root)
    short_to_qualified: dict[str, list[str]] = defaultdict(list)

    for module in summary.modules:
        index.imports[module.path] = module.imports
        alias_map = {binding.local_name: binding.source for binding in module.import_bindings}
        index.aliases[module.path] = alias_map

        for const in module.constants:
            qn = f"{module.path}:{const.name}"
            _add_symbol(
                index,
                Symbol(
                    qualified_name=qn,
                    kind="constant",
                    name=const.name,
                    path=module.path,
                    lineno=const.lineno,
                ),
            )
            short_to_qualified[const.name].append(qn)

        for cls in module.classes:
            _add_symbol(
                index,
                Symbol(
                    qualified_name=cls.qualified_name or f"{module.path}:{cls.name}",
                    kind="class",
                    name=cls.name,
                    path=module.path,
                    lineno=cls.lineno,
                    docstring=cls.docstring,
                ),
            )
            short_to_qualified[cls.name].append(cls.qualified_name)
            index.inheritance[cls.qualified_name] = cls.bases
            for method in cls.methods:
                _register_function(index, method, short_to_qualified)

        for func in module.functions:
            _register_function(index, func, short_to_qualified)

    for module in summary.modules:
        alias_map = index.aliases.get(module.path, {})
        for func in _iter_functions(module):
            caller = func.qualified_name or f"{module.path}:{func.name}"
            for raw in func.calls:
                resolved = _resolve_call(raw, module, short_to_qualified, alias_map)
                index.callees[caller].add(resolved)
                index.callers[resolved].add(caller)

    return index


def query_semantic(
    index: SemanticIndex,
    *,
    action: str,
    name: str = "",
    path: str = "",
) -> str:
    """Run a semantic query and return a model-friendly string."""
    action = action.strip().lower()
    if action in {"find", "find_symbol", "symbol", "definition", "definitions"}:
        matches = index.find_symbol(name)
        if not matches:
            return f"no symbols matching {name!r}"
        lines = [
            f"{len(matches)} symbol(s) for {name!r}:",
            "(Duplicate short names are listed separately by qualified path.)",
        ]
        for symbol in matches:
            sig = symbol.signature or ""
            doc = f" — {symbol.docstring}" if symbol.docstring else ""
            lines.append(
                f"- {symbol.kind} {symbol.qualified_name}{sig} "
                f"[{symbol.path}:{symbol.lineno}]{doc}"
            )
        return "\n".join(lines)

    if action in {"callers", "who_calls", "references"}:
        callers = index.get_callers(name)
        if not callers:
            return f"no callers found for {name!r} (best-effort name-based index)"
        return (
            f"callers of {name} (best-effort):\n"
            + "\n".join(f"- {c}" for c in callers)
        )

    if action in {"callees", "calls"}:
        callees = index.get_callees(name)
        if not callees:
            return f"no callees found for {name!r} (best-effort name-based index)"
        return (
            f"{name} calls (best-effort):\n"
            + "\n".join(f"- {c}" for c in callees)
        )

    if action in {"inheritance", "bases", "subclasses"}:
        data = index.get_inheritance(name)
        return (
            f"inheritance for {name}:\n"
            f"- bases: {', '.join(data['bases']) or '(none)'}\n"
            f"- subclasses: {', '.join(data['subclasses']) or '(none)'}"
        )

    if action in {"module", "outline"}:
        target = path or name
        outline = index.module_outline(target)
        return outline or f"no module outline for {target!r}"

    if action in {"summary", "index", "map"}:
        return index.to_markdown()

    return (
        "error: unknown action. Use one of: find, callers, callees, "
        "inheritance, module, summary, references, definition"
    )


def _register_function(
    index: SemanticIndex,
    func: FunctionSummary,
    short_to_qualified: dict[str, list[str]],
) -> None:
    qn = func.qualified_name
    local = qn.split(":", 1)[-1]
    if "." in local and local.count(".") >= 2:
        kind = "nested_function"
    elif "." in local:
        kind = "method"
    else:
        kind = "function"
    _add_symbol(
        index,
        Symbol(
            qualified_name=qn,
            kind=kind,
            name=func.name,
            path=qn.split(":", 1)[0],
            lineno=func.lineno,
            signature=func.signature,
            docstring=func.docstring,
        ),
    )
    short_to_qualified[func.name].append(qn)
    for nested in func.nested:
        _register_function(index, nested, short_to_qualified)


def _add_symbol(index: SemanticIndex, symbol: Symbol) -> None:
    index.symbols[symbol.qualified_name] = symbol
    index.by_name.setdefault(symbol.name, []).append(symbol.qualified_name)


def _iter_functions(module: ModuleSummary) -> Iterable[FunctionSummary]:
    def walk(funcs: Iterable[FunctionSummary]) -> Iterable[FunctionSummary]:
        for func in funcs:
            yield func
            yield from walk(func.nested)

    yield from walk(module.functions)
    for cls in module.classes:
        yield from walk(cls.methods)


def _resolve_call(
    raw: str,
    module: ModuleSummary,
    short_to_qualified: dict[str, list[str]],
    alias_map: dict[str, str],
) -> str:
    """Best-effort resolve a call label to a qualified symbol name."""
    # Resolve import aliases: alias.attr -> source.attr
    if "." in raw:
        head, tail = raw.split(".", 1)
        if head in alias_map:
            raw = f"{alias_map[head]}.{tail}"
    elif raw in alias_map:
        raw = alias_map[raw]

    short = raw.split(".")[-1]
    local = [qn for qn in short_to_qualified.get(short, []) if qn.startswith(module.path + ":")]
    if len(local) == 1:
        return local[0]
    # Prefer exact qualified suffix match when ambiguous
    suffix_matches = [qn for qn in short_to_qualified.get(short, []) if qn.endswith(":" + raw) or qn.endswith("." + short)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    candidates = short_to_qualified.get(short, [])
    if len(candidates) == 1:
        return candidates[0]
    # Leave unresolved / ambiguous labels marked
    if len(candidates) > 1:
        return f"{raw}?"
    return raw
