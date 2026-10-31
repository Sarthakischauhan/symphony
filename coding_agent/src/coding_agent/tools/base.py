"""Tool base: working-directory relative paths, schema generation, validation."""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Annotated, Any, ClassVar, Dict, Type

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

from core_harness import Tool


def _strip_path(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("path must be a non-empty string")
    return stripped


# A path argument with surrounding whitespace removed. Use it on models that
# keep str_strip_whitespace off so file content stays whitespace-exact.
NonEmptyPath = Annotated[str, AfterValidator(_strip_path)]


class WorkspaceTool(Tool, ABC):
    """File/shell tool. Relative paths start at the working directory."""

    name: str
    description: str
    args_model: ClassVar[Type[BaseModel]]

    def __init__(self, workspace: str | Path, *, parallel: bool = False) -> None:
        """``parallel`` marks a read-only tool the harness may batch with others.

        The harness caps a batch at ``max_parallel_tool_calls``; tools that write
        or run commands must leave this ``False`` so they stay serial.
        """
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        super().__init__(
            name=type(self).name,
            description=type(self).description,
            parameters=self.parameters_schema(),
            parallel=parallel,
        )

    def resolve_path(self, path: str) -> Path:
        """Resolve ``path``. Absolute and ``~`` paths are used as-is; others join the working directory."""
        if not isinstance(path, str):
            raise TypeError(f"path must be a string, got {type(path).__name__}")
        stripped = path.strip()
        if not stripped:
            raise ValueError("path must be a non-empty string")
        candidate = Path(stripped).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return candidate.resolve()

    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema for tool arguments. ``activity.verb`` and ``reason`` are required."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("type", "object")
        schema.setdefault("additionalProperties", False)
        properties = schema.setdefault("properties", {})
        properties["activity"] = {
            "type": "object",
            "description": (
                "Required UI context. Put it only in this nested object, never as "
                "top-level verb, reason, goal, or group. activity.verb is a short "
                "present-participle label such as 'Searching' or 'Reading'. "
                "activity.reason says why this call is needed. activity.group is an "
                "optional stable label shared by related calls."
            ),
            "properties": {
                "verb": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Short present-participle label, e.g. Searching, Reading.",
                },
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Why this call is needed.",
                },
                "group": {
                    "type": "string",
                    "description": "Stable label shared by related calls.",
                },
            },
            "required": ["verb", "reason"],
            "additionalProperties": False,
        }
        required = schema.setdefault("required", [])
        if "activity" not in required:
            required.append("activity")
        return schema

    def validate_args(self, **kwargs: Any) -> BaseModel:
        """Validate and coerce tool kwargs with the tool's pydantic args model."""
        try:
            return self.args_model.model_validate(kwargs)
        except ValidationError as exc:
            raise ValueError(f"invalid {self.name} arguments: {exc}") from exc

    def prepare_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Drop the activity label before validation.

        A model call must carry activity.verb and activity.reason; the harness
        checks that before it reaches here. A direct call may omit it. The tool
        body never sees the label, and a flattened verb or reason at the top
        level does not count as one.
        """
        prepared = dict(args)
        for key in ("activity", "verb", "reason", "goal", "group"):
            prepared.pop(key, None)
        return prepared

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> str | list[dict[str, Any]]:
        """Execute the tool and return a string or multimodal content for the model."""

    async def execute(self, *, sink: Any, args: Dict[str, Any]) -> Any:
        run_signature = inspect.signature(self.run)
        accepts_sink = "sink" in run_signature.parameters
        validated = self.validate_args(**self.prepare_args(args))
        kwargs = {**validated.model_dump(), **({"sink": sink} if accepts_sink else {})}
        if self.parallel and not inspect.iscoroutinefunction(self.run):
            # Parallel tools run off the event loop so a batch actually overlaps.
            result = await asyncio.to_thread(self.run, **kwargs)
        else:
            result = self.run(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def as_harness_tool(self) -> Tool:
        """Return ``self`` — these tools already are harness tools."""
        return self


class ToolArgsModel(BaseModel):
    """Strict base for tool argument models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
