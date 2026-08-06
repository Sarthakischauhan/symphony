"""Backward-compatible AST helpers built on RepositoryContextProvider."""

from __future__ import annotations

from pathlib import Path

from coding_agent.ast.models import CodebaseSummary


def build_ast_context(
    root: str | Path,
    *,
    max_docstring_chars: int = 160,
    max_imports_per_module: int = 20,
    include_semantic: bool = True,
    max_chars: int = 2500,
) -> str:
    """Render a token-budgeted repository map (details via ast_query)."""
    del max_docstring_chars, max_imports_per_module  # kept for API compatibility
    from coding_agent.context.provider import RepositoryContextProvider

    provider = RepositoryContextProvider(root, max_map_chars=max_chars)
    body = provider.repo_map(max_chars=max_chars)
    if not include_semantic:
        return body
    semantic_md = provider.index().to_markdown(max_symbols=16, max_edges=8)
    if not semantic_md:
        return body
    combined = f"{body}\n\n{semantic_md}"
    if len(combined) > max_chars:
        return combined[: max_chars - 3].rstrip() + "..."
    return combined


def summarize_codebase(
    root: str | Path,
    *,
    max_docstring_chars: int = 160,
    max_imports_per_module: int = 20,
) -> CodebaseSummary:
    """Return a structured summary via the cached provider."""
    del max_docstring_chars, max_imports_per_module
    from coding_agent.context.provider import RepositoryContextProvider

    provider = RepositoryContextProvider(root)
    provider.refresh()
    return provider.summary()
