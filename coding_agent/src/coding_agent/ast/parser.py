"""Python AST summarizer used to seed coding-agent context."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from coding_agent.ast.models import (
    ClassSummary,
    CodebaseSummary,
    FunctionSummary,
    ModuleSummary,
)
from coding_agent.utils.ignore_file import DEFAULT_SKIP_DIRS


def build_ast_context(
    root: str | Path,
    *,
    max_docstring_chars: int = 160,
    max_imports_per_module: int = 20,
    include_semantic: bool = True,
) -> str:
    """Parse Python files below ``root`` and render a concise Markdown summary."""
    summary = summarize_codebase(
        root,
        max_docstring_chars=max_docstring_chars,
        max_imports_per_module=max_imports_per_module,
    )
    body = summary.to_markdown()
    if not include_semantic:
        return body

    from coding_agent.ast.semantic import build_semantic_index

    semantic = build_semantic_index(summary)
    semantic_md = semantic.to_markdown()
    if not semantic_md:
        return body
    return f"{body}\n\n{semantic_md}\n"


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

    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if any(part in DEFAULT_SKIP_DIRS or part == ".symphony" for part in parts):
            continue
        if any(part.startswith(".") for part in parts[:-1]):
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
    constants = _module_constants(tree)
    classes = []
    functions = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(
                _class_summary(
                    node,
                    module_path=relative_path,
                    max_docstring_chars=max_docstring_chars,
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                _function_summary(
                    node,
                    module_path=relative_path,
                    owner=None,
                    max_docstring_chars=max_docstring_chars,
                )
            )

    return ModuleSummary(
        path=relative_path,
        docstring=_clean_docstring(ast.get_docstring(tree), max_docstring_chars),
        imports=tuple(imports),
        classes=tuple(classes),
        functions=tuple(functions),
        constants=tuple(constants),
    )


def _class_summary(
    node: ast.ClassDef,
    *,
    module_path: str,
    max_docstring_chars: int,
) -> ClassSummary:
    qualified = f"{module_path}:{node.name}"
    methods = tuple(
        _function_summary(
            child,
            module_path=module_path,
            owner=node.name,
            max_docstring_chars=max_docstring_chars,
        )
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return ClassSummary(
        name=node.name,
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        bases=tuple(_safe_unparse(base) for base in node.bases),
        docstring=_clean_docstring(ast.get_docstring(node), max_docstring_chars),
        decorators=tuple(_safe_unparse(d) for d in node.decorator_list),
        methods=methods,
        qualified_name=qualified,
    )


def _function_summary(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module_path: str,
    owner: str | None,
    max_docstring_chars: int,
) -> FunctionSummary:
    if owner:
        qualified = f"{module_path}:{owner}.{node.name}"
    else:
        qualified = f"{module_path}:{node.name}"
    return FunctionSummary(
        name=node.name,
        signature=_signature(node),
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        docstring=_clean_docstring(ast.get_docstring(node), max_docstring_chars),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=tuple(_safe_unparse(d) for d in node.decorator_list),
        calls=_collect_calls(node),
        qualified_name=qualified,
    )


def _collect_calls(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    max_calls: int = 24,
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        label = _call_label(child.func)
        if not label or label in seen:
            continue
        seen.add(label)
        names.append(label)
        if len(names) >= max_calls:
            break
    return tuple(names)


def _call_label(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_label(node.value)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


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


def _module_constants(tree: ast.Module, *, max_constants: int = 20) -> list[str]:
    constants: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper():
            continue
        constants.append(f"{name}={_safe_unparse(node.value)}")
        if len(constants) >= max_constants:
            break
    return constants


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
