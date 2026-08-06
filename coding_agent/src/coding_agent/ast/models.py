"""AST summary dataclasses for the coding agent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConstantSummary:
    """A module-level UPPER_CASE assignment."""

    name: str
    value: str
    lineno: int


@dataclass(frozen=True)
class ImportBinding:
    """An import name as seen in the module namespace (including aliases)."""

    local_name: str
    source: str
    lineno: int


@dataclass(frozen=True)
class FunctionSummary:
    """A function or method (including nested functions)."""

    name: str
    signature: str
    lineno: int
    end_lineno: int | None = None
    docstring: str | None = None
    is_async: bool = False
    decorators: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    qualified_name: str = ""
    nested: tuple["FunctionSummary", ...] = ()


@dataclass(frozen=True)
class ClassSummary:
    """A Python class and its direct methods."""

    name: str
    lineno: int
    end_lineno: int | None = None
    bases: tuple[str, ...] = ()
    docstring: str | None = None
    decorators: tuple[str, ...] = ()
    methods: tuple[FunctionSummary, ...] = ()
    qualified_name: str = ""


@dataclass(frozen=True)
class ModuleSummary:
    """A parsed source module (language-agnostic enough for future indexers)."""

    path: str
    docstring: str | None = None
    imports: tuple[str, ...] = ()
    import_bindings: tuple[ImportBinding, ...] = ()
    classes: tuple[ClassSummary, ...] = ()
    functions: tuple[FunctionSummary, ...] = ()
    constants: tuple[ConstantSummary, ...] = ()
    errors: tuple[str, ...] = ()
    language: str = "python"


@dataclass(frozen=True)
class CodebaseSummary:
    """A collection of parsed modules rooted at a source directory."""

    root: str
    modules: tuple[ModuleSummary, ...] = field(default_factory=tuple)

    def to_markdown(self, *, max_chars: int | None = None) -> str:
        """Render a compact context block; optional hard char budget."""
        lines = [
            "Repository map:",
            f"- Root: {self.root}",
            f"- Modules: {len(self.modules)}",
            "- Call relationships are best-effort name-based (not type-checked).",
        ]

        for module in self.modules:
            lines.append("")
            lines.append(f"## {module.path}")
            if module.errors:
                for error in module.errors:
                    lines.append(f"- Parse/read error: {error}")
                continue
            if module.docstring:
                lines.append(f"- Module: {module.docstring}")
            names: list[str] = []
            names.extend(f"class {cls.name}" for cls in module.classes)
            names.extend(f"def {fn.name}" for fn in module.functions)
            names.extend(c.name for c in module.constants[:8])
            if names:
                lines.append(f"- Symbols: {', '.join(names[:24])}")
            if len(names) > 24:
                lines.append(f"- … {len(names) - 24} more (use ast_query)")

        text = "\n".join(lines)
        if max_chars is not None and len(text) > max_chars:
            return text[: max_chars - 3].rstrip() + "..."
        return text
