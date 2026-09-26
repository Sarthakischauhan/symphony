"""The typed argument contract a skill declares in its front matter.

Why: one validated shape and one renderer keep the prompt and /extensions in agreement.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ArgType = Literal["string", "number", "boolean", "enum"]
# Exact Python types YAML may produce for each default; bool is not a number.
_DEFAULT_TYPES = {"string": (str,), "number": (int, float), "boolean": (bool,), "enum": (str,)}


def fold_whitespace(text: str) -> str:
    """Collapse folded or wrapped YAML text into one prompt line."""
    return " ".join(text.split())


Description = Annotated[str, AfterValidator(fold_whitespace), Field(min_length=1, max_length=1000)]


class ExtensionArg(BaseModel):
    """One declared argument; strict so a typo in a key fails loudly instead of vanishing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    type: ArgType
    description: Description
    required: bool = False
    default: str | int | float | bool | None = None
    options: tuple[str, ...] = Field(default=(), alias="enum")

    @model_validator(mode="after")
    def _check_enum_and_default(self) -> ExtensionArg:
        if (self.type == "enum") != bool(self.options) or len(self.options) == 1 or "" in self.options:
            raise ValueError(f"argument {self.name}: type enum needs two or more options; other types take none")
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"argument {self.name} has duplicate enum options")
        if self.default is None:
            return self
        if self.required:
            raise ValueError(f"argument {self.name} is required and cannot have a default")
        if type(self.default) not in _DEFAULT_TYPES[self.type]:
            raise ValueError(f"argument {self.name} default does not match type {self.type}")
        if self.options and self.default not in self.options:
            raise ValueError(f"argument {self.name} default is not in its enum")
        return self


def _unique_names(args: tuple[ExtensionArg, ...]) -> tuple[ExtensionArg, ...]:
    if len({arg.name for arg in args}) != len(args):
        raise ValueError("duplicate argument name")
    return args


ExtensionArgs = Annotated[tuple[ExtensionArg, ...], AfterValidator(_unique_names)]


def render_args(args: tuple[ExtensionArg, ...]) -> str:
    """Render args as ``name: type[a|b]=default required``, comma separated."""
    return ", ".join(
        f"{arg.name}: {arg.type}"
        + (f"[{'|'.join(arg.options)}]" if arg.options else "")
        + (
            f"={str(arg.default).lower() if isinstance(arg.default, bool) else arg.default}"
            if arg.default not in (None, "")
            else ""
        )
        + (" required" if arg.required else "")
        for arg in args
    )


__all__ = ["ArgType", "Description", "ExtensionArg", "ExtensionArgs", "render_args"]
