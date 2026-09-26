"""Split and validate the YAML front matter at the top of a SKILL.md.

Why: skill files come from user directories and are pasted into the prompt,
so the YAML is untrusted. It is size-capped, loaded without aliases, and
reduced to the three keys the catalog reads: name, description, and args.
"""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, ConfigDict, Field

from coding_agent.extension_args import Description, ExtensionArgs

SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_MAX_FRONT_MATTER_BYTES = 4096


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that rejects YAML aliases (``*name``)."""

    def compose_node(self, parent, index):
        # WHY: aliases expand exponentially ("billion laughs"); 353 bytes of
        # front matter took 50s at startup. Skills never need them.
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not allowed in front matter")
        return super().compose_node(parent, index)


class _SkillFrontMatter(BaseModel):
    """The keys the catalog reads; other standard keys such as allowed-tools are ignored."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=SKILL_NAME.pattern, max_length=1000)
    description: Description
    args: ExtensionArgs = ()


def read_front_matter(text: str) -> _SkillFrontMatter:
    """Validate the leading ``---`` block of a SKILL.md."""
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError("SKILL.md must start with a closed YAML front matter block")
    if len(match.group(1).encode()) > _MAX_FRONT_MATTER_BYTES:
        raise ValueError(f"front matter exceeds the {_MAX_FRONT_MATTER_BYTES} byte limit")
    try:
        data = yaml.load(match.group(1), Loader=_NoAliasLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f"invalid YAML front matter: {exc}") from exc
    return _SkillFrontMatter.model_validate(data)


__all__ = ["SKILL_NAME", "read_front_matter"]
