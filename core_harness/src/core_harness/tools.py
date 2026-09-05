"""Callable adapter that exposes a Python function as an agent tool."""

import inspect
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional


current_tool_call_id: ContextVar[str] = ContextVar("tool_call_id", default="")


class Tool:
    """Wrap a Python callable and expose an LLM-friendly tool schema.

    Subclasses may omit ``func`` and override :meth:`execute` instead.
    """

    def __init__(
        self,
        func: Optional[Callable[..., Any]] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
    ) -> None:
        self.func = func
        self.name = name or (func.__name__ if func is not None else "")
        self.description = (
            description
            or (inspect.getdoc(func) if func is not None else None)
            or "No description provided."
        )
        self.signature = inspect.signature(func) if func is not None else None
        self.parameters = parameters
        self.parallel = parallel

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters if self.parameters is not None else self._infer_parameters(),
        }

    def _infer_parameters(self) -> Dict[str, Any]:
        if self.signature is None:
            return {"type": "object", "properties": {}, "required": []}
        properties: Dict[str, Dict[str, Any]] = {}
        required: list[str] = []
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            dict: "object",
            list: "array",
        }
        for param_name, param in self.signature.parameters.items():
            if param_name == "control_plane":
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
            properties[param_name] = {
                "type": type_map.get(annotation, "string"),
                "description": f"Parameter {param_name}",
            }
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
        return {"type": "object", "properties": properties, "required": required}

    async def execute(self, *, control_plane: Any, args: Dict[str, Any]) -> Any:
        if self.func is None:
            raise NotImplementedError(f"{type(self).__name__}.execute")
        kwargs: Dict[str, Any] = {}
        accepts_var_keyword = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in self.signature.parameters.values()  # type: ignore[union-attr]
        )
        for param_name, param in self.signature.parameters.items():  # type: ignore[union-attr]
            if param_name == "control_plane":
                kwargs[param_name] = control_plane
            elif param.kind != inspect.Parameter.VAR_KEYWORD and param_name in args:
                kwargs[param_name] = args[param_name]
        if accepts_var_keyword:
            for key, value in args.items():
                if key not in kwargs:
                    kwargs[key] = value
        if inspect.iscoroutinefunction(self.func):
            return await self.func(**kwargs)
        return self.func(**kwargs)


__all__ = ["Tool"]
