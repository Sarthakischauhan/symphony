"""Shared workspace binding, schema generation, and input validation."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Dict, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from core_harness import Tool


class WorkspaceTool(Tool, ABC):
    """Workspace-scoped tool. Instances are harness tools; no extra wrapper."""

    name: str
    description: str
    args_model: ClassVar[Type[BaseModel]]

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        super().__init__(
            name=type(self).name,
            description=type(self).description,
            parameters=self.parameters_schema(),
        )

    def resolve_path(self, path: str) -> Path:
        """Resolve a workspace-relative path; reject escapes and bad types."""
        if not isinstance(path, str):
            raise TypeError(f"path must be a string, got {type(path).__name__}")
        if not path.strip():
            raise ValueError("path must be a non-empty string")

        target = (self.workspace / path).resolve()
        if not target.is_relative_to(self.workspace):
            raise ValueError(f"Path escapes workspace: {path}")
        return target

    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema for tool arguments (OpenAI-compatible parameters object)."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("type", "object")
        schema.setdefault("additionalProperties", False)
        return schema

    def validate_args(self, **kwargs: Any) -> BaseModel:
        """Validate and coerce tool kwargs with the tool's pydantic args model."""
        try:
            return self.args_model.model_validate(kwargs)
        except ValidationError as exc:
            raise ValueError(f"invalid {self.name} arguments: {exc}") from exc

    def prepare_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Apply instance configuration before schema validation."""
        return dict(args)

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> str | list[dict[str, Any]]:
        """Execute the tool and return a string or multimodal content for the model."""

    async def execute(self, *, control_plane: Any, args: Dict[str, Any]) -> Any:
        run_signature = inspect.signature(self.run)
        accepts_control_plane = "control_plane" in run_signature.parameters
        validated = self.validate_args(**self.prepare_args(args))
        result = self.run(
            **validated.model_dump(),
            **({"control_plane": control_plane} if accepts_control_plane else {}),
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    def as_harness_tool(self) -> Tool:
        """Return ``self`` — workspace tools already are harness tools."""
        return self


class ToolArgsModel(BaseModel):
    """Strict base for tool argument models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
