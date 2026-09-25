"""YAML front matter for skills.

Lives in the skills package. Plugin manifests reuse ``parse_args`` for the
same argument contract. The loader keeps name, description, and args.
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from coding_agent.skills.models import SkillArg

_NAME = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
_ARG_NAME = r"^[a-z][a-z0-9_]*$"


class _ArgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_ARG_NAME, max_length=64)
    type: Literal["string", "number", "boolean", "enum"]
    description: str = Field(min_length=1, max_length=500)
    required: bool = False
    default: str | int | float | bool | None = None
    enum: list[str] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "_ArgModel":
        if self.type == "enum":
            options = self.enum or []
            if len(options) < 2 or any(not isinstance(item, str) or not item for item in options):
                raise ValueError(f"argument {self.name} needs at least two enum options")
            if self.default is not None and self.default not in options:
                raise ValueError(f"argument {self.name} default is not in its enum")
        elif self.enum is not None:
            raise ValueError(f"argument {self.name} enum list is only valid for type enum")
        if self.default is not None and not _default_matches(self.type, self.default):
            raise ValueError(f"argument {self.name} default does not match its type")
        return self


class _SkillFrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME, min_length=1, max_length=1000)
    description: str = Field(min_length=1, max_length=1000)
    args: list[_ArgModel] = Field(default_factory=list)


def parse_args(value: object) -> tuple[SkillArg, ...]:
    """Validate an args list from YAML front matter or a plugin manifest."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("args must be a list")
    parsed = [_ArgModel.model_validate(item) for item in value]
    names = [arg.name for arg in parsed]
    if len(names) != len(set(names)):
        raise ValueError("duplicate argument name")
    return tuple(_to_arg(arg) for arg in parsed)


def parse_skill_front_matter(text: str) -> tuple[str, str, tuple[SkillArg, ...]]:
    """Load name, description, and args from a YAML front-matter document."""
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("front matter must be a YAML map")
    meta = _SkillFrontMatter.model_validate(loaded)
    names = [arg.name for arg in meta.args]
    if len(names) != len(set(names)):
        raise ValueError("duplicate argument name")
    return meta.name, " ".join(meta.description.split()), tuple(_to_arg(arg) for arg in meta.args)


def _to_arg(arg: _ArgModel) -> SkillArg:
    return SkillArg(
        name=arg.name,
        type=arg.type,
        description=arg.description,
        required=arg.required,
        default=arg.default,
        options=tuple(arg.enum or ()),
    )


def _default_matches(kind: str, value: object) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "enum":
        return isinstance(value, str)
    return False


__all__ = ["parse_args", "parse_skill_front_matter"]
