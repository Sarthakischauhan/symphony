import inspect
from typing import Any, Callable, Dict, Optional


class Tool:
    """Wrap a Python callable and expose an LLM-friendly tool schema."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        self.func = func
        self.name = name or func.__name__
        self.description = description or inspect.getdoc(func) or "No description provided."
        self.signature = inspect.signature(func)

    def get_schema(self) -> Dict[str, Any]:
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

            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
            properties[param_name] = {
                "type": type_map.get(annotation, "string"),
                "description": f"Parameter {param_name}",
            }
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    async def execute(self, *, control_plane: Any, args: Dict[str, Any]) -> Any:
        kwargs: Dict[str, Any] = {}

        for param_name in self.signature.parameters:
            if param_name == "control_plane":
                kwargs[param_name] = control_plane
            elif param_name in args:
                kwargs[param_name] = args[param_name]

        if inspect.iscoroutinefunction(self.func):
            return await self.func(**kwargs)

        return self.func(**kwargs)

