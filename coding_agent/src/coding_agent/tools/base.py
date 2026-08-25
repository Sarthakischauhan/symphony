"""Shared workspace binding, schema generation, and input validation."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Dict, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from core_harness import Tool


class WorkspaceTool(ABC):
    """Base class for tools scoped to a workspace root."""

    name: str
    description: str
    args_model: ClassVar[Type[BaseModel]]

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

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

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> str | list[dict[str, Any]]:
        """Execute the tool and return a string or multimodal content for the model."""

    def as_harness_tool(self) -> Tool:
        """Wrap ``run`` as a ``core_harness.Tool`` with explicit JSON schema."""
        tool = self
        run_signature = inspect.signature(self.run)
        accepts_control_plane = "control_plane" in run_signature.parameters

        async def invoke(**kwargs: Any) -> str | list[dict[str, Any]]:
            control_plane = kwargs.pop("control_plane", None) if accepts_control_plane else None
            validated = tool.validate_args(**kwargs)
            result = tool.run(
                **validated.model_dump(),
                **({"control_plane": control_plane} if accepts_control_plane else {}),
            )
            if inspect.isawaitable(result):
                result = await result
            return result

        params = []
        for field_name, field in self.args_model.model_fields.items():
            default = (
                inspect.Parameter.empty
                if field.is_required()
                else field.default
            )
            annotation = field.annotation if field.annotation is not None else Any
            params.append(
                inspect.Parameter(
                    field_name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=annotation,
                )
            )
        if accepts_control_plane:
            params.append(
                inspect.Parameter(
                    "control_plane",
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=Any,
                )
            )
        invoke.__signature__ = inspect.Signature(params)
        invoke.__name__ = self.name
        invoke.__doc__ = self.description

        return Tool(
            invoke,
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema(),
        )


class ToolArgsModel(BaseModel):
    """Strict base for tool argument models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
