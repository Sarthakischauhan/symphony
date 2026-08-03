"""Semantic layer over AST summaries: symbols, inheritance, call graph."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from coding_agent.ast.models import CodebaseSummary, FunctionSummary, ModuleSummary


@dataclass(frozen=True)
class Symbol:
    """A named definition in the codebase."""

    qualified_name: str
    kind: str  # module | class | function | method | constant
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

    def find_symbol(self, name: str, *, limit: int = 20) -> list[Symbol]:
        """Find symbols by exact name or qualified-name substring."""
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
            # Also match by short name edges
            found.update(self.callers.get(name, set()))
        return sorted(found)

    def get_callees(self, name: str) -> list[str]:
        keys = self._resolve_keys(name)
        found: set[str] = set()
        for key in keys:
            found.update(self.callees.get(key, set()))
        if name in self.callees:
            found.update(self.callees[name])
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
        """Return a short outline for one module path if known."""
        symbols = [s for s in self.symbols.values() if s.path == path]
        if not symbols:
            return None
        lines = [f"Module {path}:"]
        for symbol in sorted(symbols, key=lambda s: (s.lineno, s.name)):
            sig = symbol.signature or ""
            lines.append(f"- {symbol.kind} {symbol.name}{sig} [line {symbol.lineno}]")
        return "\n".join(lines)

    def to_markdown(self, *, max_symbols: int = 40, max_edges: int = 30) -> str:
        if not self.symbols:
            return ""

        lines = [
            "Semantic index:",
            f"- Symbols: {len(self.symbols)}",
            f"- Inheritance edges: {len(self.inheritance)}",
            f"- Call-graph functions: {len(self.callees)}",
        ]

        # Highlight classes with bases (semantic relationships)
        inheritance_lines = []
        for qn, bases in sorted(self.inheritance.items()):
            if bases:
                inheritance_lines.append(f"- {qn} -> {', '.join(bases)}")
        if inheritance_lines:
            lines.append("")
            lines.append("Inheritance:")
            lines.extend(inheritance_lines[:max_edges])

        # Densest call relationships
        call_lines = []
        for caller, callees in sorted(self.callees.items(), key=lambda item: -len(item[1])):
            if not callees:
                continue
            shown = ", ".join(sorted(callees)[:8])
            call_lines.append(f"- {caller} calls {shown}")
            if len(call_lines) >= max_edges:
                break
        if call_lines:
            lines.append("")
            lines.append("Call graph (sample):")
            lines.extend(call_lines)

        # Symbol directory (truncated)
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
    """Build a semantic index from a codebase AST summary."""
    index = SemanticIndex(root=summary.root)

    # First pass: register symbols
    short_to_qualified: dict[str, list[str]] = defaultdict(list)
    for module in summary.modules:
        index.imports[module.path] = module.imports
        for const in module.constants:
            name = const.split("=", 1)[0]
            qn = f"{module.path}:{name}"
            _add_symbol(
                index,
                Symbol(
                    qualified_name=qn,
                    kind="constant",
                    name=name,
                    path=module.path,
                    lineno=1,
                ),
            )
            short_to_qualified[name].append(qn)

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

    # Second pass: resolve call edges against known symbols when possible
    for module in summary.modules:
        for func in _iter_functions(module):
            caller = func.qualified_name or f"{module.path}:{func.name}"
            for raw in func.calls:
                resolved = _resolve_call(raw, module, short_to_qualified)
                index.callees[caller].add(resolved)
                index.callers[resolved].add(caller)
                # Also index by short name for fuzzy queries
                short = raw.split(".")[-1]
                index.callers[short].add(caller)

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
    if action in {"find", "find_symbol", "symbol"}:
        matches = index.find_symbol(name)
        if not matches:
            return f"no symbols matching {name!r}"
        lines = [f"{len(matches)} symbol(s) for {name!r}:"]
        for symbol in matches:
            sig = symbol.signature or ""
            doc = f" — {symbol.docstring}" if symbol.docstring else ""
            lines.append(
                f"- {symbol.kind} {symbol.qualified_name}{sig} "
                f"[{symbol.path}:{symbol.lineno}]{doc}"
            )
        return "\n".join(lines)

    if action in {"callers", "who_calls"}:
        callers = index.get_callers(name)
        if not callers:
            return f"no callers found for {name!r}"
        return f"callers of {name}:\n" + "\n".join(f"- {c}" for c in callers)

    if action in {"callees", "calls"}:
        callees = index.get_callees(name)
        if not callees:
            return f"no callees found for {name!r}"
        return f"{name} calls:\n" + "\n".join(f"- {c}" for c in callees)

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

    if action in {"summary", "index"}:
        return index.to_markdown()

    return (
        "error: unknown action. Use one of: find, callers, callees, "
        "inheritance, module, summary"
    )


def _register_function(
    index: SemanticIndex,
    func: FunctionSummary,
    short_to_qualified: dict[str, list[str]],
) -> None:
    qn = func.qualified_name
    kind = "method" if "." in qn.split(":", 1)[-1] else "function"
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


def _add_symbol(index: SemanticIndex, symbol: Symbol) -> None:
    index.symbols[symbol.qualified_name] = symbol
    index.by_name.setdefault(symbol.name, []).append(symbol.qualified_name)


def _iter_functions(module: ModuleSummary) -> Iterable[FunctionSummary]:
    yield from module.functions
    for cls in module.classes:
        yield from cls.methods


def _resolve_call(
    raw: str,
    module: ModuleSummary,
    short_to_qualified: dict[str, list[str]],
) -> str:
    """Best-effort resolve a call label to a qualified symbol name."""
    short = raw.split(".")[-1]
    # Prefer same-module definitions
    local = [qn for qn in short_to_qualified.get(short, []) if qn.startswith(module.path + ":")]
    if len(local) == 1:
        return local[0]
    candidates = short_to_qualified.get(short, [])
    if len(candidates) == 1:
        return candidates[0]
    return raw
