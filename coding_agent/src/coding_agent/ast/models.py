"""AST summary dataclasses for the coding agent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FunctionSummary:
    """A top-level function or class method."""

    name: str
    signature: str
    lineno: int
    end_lineno: int | None = None
    docstring: str | None = None
    is_async: bool = False
    decorators: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    qualified_name: str = ""


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
    """A parsed Python module."""

    path: str
    docstring: str | None = None
    imports: tuple[str, ...] = ()
    classes: tuple[ClassSummary, ...] = ()
    functions: tuple[FunctionSummary, ...] = ()
    constants: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodebaseSummary:
    """A collection of parsed modules rooted at a source directory."""

    root: str
    modules: tuple[ModuleSummary, ...] = field(default_factory=tuple)

    def to_markdown(self) -> str:
        """Render a compact context block suitable for a system prompt."""
        lines = [
            "Codebase AST context:",
            f"- Root: {self.root}",
            f"- Python modules: {len(self.modules)}",
        ]

        for module in self.modules:
            lines.append("")
            lines.append(f"## {module.path}")
            if module.docstring:
                lines.append(f"- Module: {module.docstring}")
            if module.imports:
                lines.append(f"- Imports: {', '.join(module.imports)}")
            if module.constants:
                lines.append(f"- Constants: {', '.join(module.constants)}")
            for cls in module.classes:
                base_text = f"({', '.join(cls.bases)})" if cls.bases else ""
                deco = f" @{', @'.join(cls.decorators)}" if cls.decorators else ""
                lines.append(f"- class {cls.name}{base_text}{deco} [line {cls.lineno}]")
                if cls.docstring:
                    lines.append(f"  - {cls.docstring}")
                for method in cls.methods:
                    method_prefix = "async def" if method.is_async else "def"
                    mdeco = (
                        f" @{', @'.join(method.decorators)}" if method.decorators else ""
                    )
                    lines.append(
                        f"  - {method_prefix} {method.name}{method.signature}{mdeco} "
                        f"[line {method.lineno}]"
                    )
                    if method.docstring:
                        lines.append(f"    - {method.docstring}")
                    if method.calls:
                        lines.append(f"    - calls: {', '.join(method.calls[:12])}")
            for func in module.functions:
                function_prefix = "async def" if func.is_async else "def"
                fdeco = f" @{', @'.join(func.decorators)}" if func.decorators else ""
                lines.append(
                    f"- {function_prefix} {func.name}{func.signature}{fdeco} "
                    f"[line {func.lineno}]"
                )
                if func.docstring:
                    lines.append(f"  - {func.docstring}")
                if func.calls:
                    lines.append(f"  - calls: {', '.join(func.calls[:12])}")
            for error in module.errors:
                lines.append(f"- Parse error: {error}")

        return "\n".join(lines)
