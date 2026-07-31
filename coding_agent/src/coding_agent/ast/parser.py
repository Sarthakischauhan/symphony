"""Small Python AST summarizer used to seed coding-agent context."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FunctionSummary:
    """A top-level function or class method."""

    name: str
    signature: str
    lineno: int
    docstring: str | None = None
    is_async: bool = False


@dataclass(frozen=True)
class ClassSummary:
    """A Python class and its direct methods."""

    name: str
    lineno: int
    bases: tuple[str, ...] = ()
    docstring: str | None = None
    methods: tuple[FunctionSummary, ...] = ()


@dataclass(frozen=True)
class ModuleSummary:
    """A parsed Python module."""

    path: str
    docstring: str | None = None
    imports: tuple[str, ...] = ()
    classes: tuple[ClassSummary, ...] = ()
    functions: tuple[FunctionSummary, ...] = ()
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
            for cls in module.classes:
                base_text = f"({', '.join(cls.bases)})" if cls.bases else ""
                lines.append(f"- class {cls.name}{base_text} [line {cls.lineno}]")
                if cls.docstring:
                    lines.append(f"  - {cls.docstring}")
                for method in cls.methods:
                    method_prefix = "async def" if method.is_async else "def"
                    lines.append(
                        f"  - {method_prefix} {method.name}{method.signature} [line {method.lineno}]"
                    )
                    if method.docstring:
                        lines.append(f"    - {method.docstring}")
            for func in module.functions:
                function_prefix = "async def" if func.is_async else "def"
                lines.append(
                    f"- {function_prefix} {func.name}{func.signature} [line {func.lineno}]"
                )
                if func.docstring:
                    lines.append(f"  - {func.docstring}")
            for error in module.errors:
                lines.append(f"- Parse error: {error}")

        return "\n".join(lines)


def build_ast_context(
    root: str | Path,
    *,
    max_docstring_chars: int = 160,
    max_imports_per_module: int = 20,
) -> str:
    """Parse Python files below ``root`` and render a concise Markdown summary."""
    return summarize_codebase(
        root,
        max_docstring_chars=max_docstring_chars,
        max_imports_per_module=max_imports_per_module,
    ).to_markdown()


def summarize_codebase(
    root: str | Path,
    *,
    max_docstring_chars: int = 160,
    max_imports_per_module: int = 20,
) -> CodebaseSummary:
    """Return a structured AST summary for all Python files under ``root``."""
    root_path = Path(root).resolve()
    modules = tuple(
        _summarize_module(
            path,
            root_path=root_path,
            max_docstring_chars=max_docstring_chars,
            max_imports_per_module=max_imports_per_module,
        )
        for path in _iter_python_files(root_path)
    )
    return CodebaseSummary(root=str(root_path), modules=modules)


def _iter_python_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return

    ignored_dirs = {
        "__pycache__",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "venv",
    }
    for path in sorted(root.rglob("*.py")):
        if any(part in ignored_dirs for part in path.parts):
            continue
        yield path


def _summarize_module(
    path: Path,
    *,
    root_path: Path,
    max_docstring_chars: int,
    max_imports_per_module: int,
) -> ModuleSummary:
    relative_path = _relative_path(path, root_path)
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return ModuleSummary(
            path=relative_path,
            errors=(f"unable to decode UTF-8: {exc}",),
        )

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        message = f"{exc.msg} at line {exc.lineno}"
        return ModuleSummary(path=relative_path, errors=(message,))

    imports = _module_imports(tree)[:max_imports_per_module]
    classes = []
    functions = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(_class_summary(node, max_docstring_chars=max_docstring_chars))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                _function_summary(node, max_docstring_chars=max_docstring_chars)
            )

    return ModuleSummary(
        path=relative_path,
        docstring=_clean_docstring(ast.get_docstring(tree), max_docstring_chars),
        imports=tuple(imports),
        classes=tuple(classes),
        functions=tuple(functions),
    )


def _class_summary(node: ast.ClassDef, *, max_docstring_chars: int) -> ClassSummary:
    methods = tuple(
        _function_summary(child, max_docstring_chars=max_docstring_chars)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return ClassSummary(
        name=node.name,
        lineno=node.lineno,
        bases=tuple(_safe_unparse(base) for base in node.bases),
        docstring=_clean_docstring(ast.get_docstring(node), max_docstring_chars),
        methods=methods,
    )


def _function_summary(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    max_docstring_chars: int,
) -> FunctionSummary:
    return FunctionSummary(
        name=node.name,
        signature=_signature(node),
        lineno=node.lineno,
        docstring=_clean_docstring(ast.get_docstring(node), max_docstring_chars),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _module_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names = ", ".join(alias.name for alias in node.names)
            imports.append(f"{module} import {names}")
    return imports


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    params: list[str] = []

    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        if index == len(args.posonlyargs) and args.posonlyargs:
            params.append("/")
        params.append(_format_arg(arg, default))

    if args.vararg:
        params.append("*" + _format_arg(args.vararg, None))
    elif args.kwonlyargs:
        params.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(_format_arg(arg, default))

    if args.kwarg:
        params.append("**" + _format_arg(args.kwarg, None))

    returns = f" -> {_safe_unparse(node.returns)}" if node.returns else ""
    return f"({', '.join(params)}){returns}"


def _format_arg(arg: ast.arg, default: ast.expr | None) -> str:
    annotation = f": {_safe_unparse(arg.annotation)}" if arg.annotation else ""
    default_text = f"={_safe_unparse(default)}" if default is not None else ""
    return f"{arg.arg}{annotation}{default_text}"


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return "None"
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


def _clean_docstring(docstring: str | None, max_chars: int) -> str | None:
    if not docstring:
        return None
    compact = " ".join(docstring.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
