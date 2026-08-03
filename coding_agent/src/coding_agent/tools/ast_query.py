"""Query the semantic AST index for the workspace."""

from __future__ import annotations

from pydantic import Field

from coding_agent.ast.parser import summarize_codebase
from coding_agent.ast.semantic import build_semantic_index, query_semantic
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class AstQueryArgs(ToolArgsModel):
    action: str = Field(
        ...,
        min_length=1,
        description=(
            "Semantic query type: find | callers | callees | inheritance | "
            "module | summary"
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
        "Query a semantic AST index of the workspace Python code: find symbols, "
        "callers/callees, inheritance, or module outlines. Prefer this before "
        "large read_file sweeps when you need structure."
    )
    args_model = AstQueryArgs

    def run(self, action: str, name: str = "", path: str = "") -> str:
        try:
            summary = summarize_codebase(self.workspace)
            index = build_semantic_index(summary)
            return query_semantic(index, action=action, name=name, path=path)
        except Exception as exc:  # noqa: BLE001 — return tool error to the model
            return f"error: ast_query failed: {exc}"
