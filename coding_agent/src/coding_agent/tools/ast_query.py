"""Query the cached semantic repository index."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

if TYPE_CHECKING:
    from coding_agent.context.provider import RepositoryContextProvider


class AstQueryArgs(ToolArgsModel):
    action: str = Field(
        ...,
        min_length=1,
        description=(
            "Semantic query type: find | definition | callers | references | "
            "callees | inheritance | module | summary"
        ),
    )
    name: str = Field(
        default="",
        description="Symbol or module name for the query (e.g. 'CodingAgent', 'run').",
    )
    path: str = Field(
        default="",
        description="Optional module path for action=module (e.g. 'pkg/mod.py').",
    )


class AstQueryTool(WorkspaceTool):
    name = "ast_query"
    description = (
        "Query a cached semantic repository index: find symbols/definitions, "
        "callers/references, callees, inheritance, or module outlines. "
        "Call relationships are best-effort name-based. Prefer this before "
        "large read_file sweeps when you need structure."
    )
    args_model = AstQueryArgs

    def __init__(self, workspace: str | Path) -> None:
        super().__init__(workspace)
        self._context_provider: Optional["RepositoryContextProvider"] = None

    def bind_context_provider(self, provider: "RepositoryContextProvider") -> None:
        self._context_provider = provider

    def run(self, action: str, name: str = "", path: str = "") -> str:
        try:
            provider = self._context_provider
            if provider is None:
                from coding_agent.context.provider import RepositoryContextProvider

                provider = RepositoryContextProvider(self.workspace)
                self._context_provider = provider
            return provider.query(action=action, name=name, path=path)
        except Exception as exc:  # noqa: BLE001 — return tool error to the model
            return f"error: ast_query failed: {exc}"
