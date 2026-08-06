"""Python-AST indexer implementing RepositoryIndexer.

Replaceable later by Tree-sitter or LSP backends with the same ModuleSummary shape.
"""

from __future__ import annotations

import ast

from coding_agent.ast.models import (
    ClassSummary,
    ConstantSummary,
    FunctionSummary,
    ImportBinding,
    ModuleSummary,
)


class PythonAstIndexer:
    """Parse Python source into ModuleSummary structures."""

    language = "python"
    extensions: tuple[str, ...] = (".py",)

    def parse_file(self, *, path: str, source: str) -> ModuleSummary:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            message = f"{exc.msg} at line {exc.lineno}"
            return ModuleSummary(path=path, errors=(message,), language=self.language)
        except Exception as exc:  # noqa: BLE001
            return ModuleSummary(
                path=path,
                errors=(f"parse failed: {exc}",),
                language=self.language,
            )

        return ModuleSummary(
            path=path,
            docstring=_clean_docstring(ast.get_docstring(tree), 160),
            imports=tuple(_module_imports(tree)[:20]),
            import_bindings=tuple(_import_bindings(tree)),
            classes=tuple(
                _class_summary(node, module_path=path)
                for node in tree.body
                if isinstance(node, ast.ClassDef)
            ),
            functions=tuple(
                _function_summary(node, module_path=path, owner=None)
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            constants=tuple(_module_constants(tree)),
            language=self.language,
        )


def _class_summary(node: ast.ClassDef, *, module_path: str) -> ClassSummary:
    qualified = f"{module_path}:{node.name}"
    methods = tuple(
        _function_summary(child, module_path=module_path, owner=node.name)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return ClassSummary(
        name=node.name,
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        bases=tuple(_safe_unparse(base) for base in node.bases),
        docstring=_clean_docstring(ast.get_docstring(node), 160),
        decorators=tuple(_safe_unparse(d) for d in node.decorator_list),
        methods=methods,
        qualified_name=qualified,
    )


def _function_summary(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module_path: str,
    owner: str | None,
) -> FunctionSummary:
    if owner:
        qualified = f"{module_path}:{owner}.{node.name}"
    else:
        qualified = f"{module_path}:{node.name}"

    nested = tuple(
        _function_summary(
            child,
            module_path=module_path,
            owner=f"{owner}.{node.name}" if owner else node.name,
        )
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    return FunctionSummary(
        name=node.name,
        signature=_signature(node),
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        docstring=_clean_docstring(ast.get_docstring(node), 160),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=tuple(_safe_unparse(d) for d in node.decorator_list),
        calls=_collect_calls(node, owner=owner),
        qualified_name=qualified,
        nested=nested,
    )


def _collect_calls(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    owner: str | None,
    max_calls: int = 24,
) -> tuple[str, ...]:
    """Best-effort call extraction (name-based, not type-checked)."""
    names: list[str] = []
    seen: set[str] = set()

    # Only walk this function body; skip nested function defs (handled separately).
    for child in node.body:
        for sub in ast.walk(child):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Avoid descending into nested function bodies via walk on outer stmts
                # by skipping Call nodes that belong to nested defs: walk still visits
                # them. Filter by comparing lineno ranges of nested defs.
                pass
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(child):
            if not isinstance(sub, ast.Call):
                continue
            # Skip calls that live inside nested function definitions.
            if _call_inside_nested(sub, node):
                continue
            label = _call_label(sub.func, owner=owner)
            if not label or label in seen:
                continue
            seen.add(label)
            names.append(label)
            if len(names) >= max_calls:
                return tuple(names)
    return tuple(names)


def _call_inside_nested(
    call: ast.Call,
    outer: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for child in outer.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = child.lineno
        end = getattr(child, "end_lineno", child.lineno) or child.lineno
        if start <= call.lineno <= end:
            return True
    return False


def _call_label(node: ast.AST, *, owner: str | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self" and owner:
            return f"{owner}.{node.attr}"
        base = _call_label(node.value, owner=owner)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


def _module_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports.append(f"{alias.name} as {alias.asname}")
                else:
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in node.names
            )
            imports.append(f"{module} import {names}")
    return imports


def _import_bindings(tree: ast.Module) -> list[ImportBinding]:
    bindings: list[ImportBinding] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                bindings.append(
                    ImportBinding(local_name=local, source=alias.name, lineno=node.lineno)
                )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                local = alias.asname or alias.name
                bindings.append(
                    ImportBinding(
                        local_name=local,
                        source=f"{module}.{alias.name}".rstrip("."),
                        lineno=node.lineno,
                    )
                )
    return bindings


def _module_constants(tree: ast.Module, *, max_constants: int = 20) -> list[ConstantSummary]:
    constants: list[ConstantSummary] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper():
            continue
        constants.append(
            ConstantSummary(
                name=name,
                value=_safe_unparse(node.value),
                lineno=node.lineno,
            )
        )
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
