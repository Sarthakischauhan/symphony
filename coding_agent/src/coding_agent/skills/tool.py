"""Load a skill's instructions on demand instead of carrying them in every prompt."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from coding_agent.skills.args import render_args
from coding_agent.skills.registry import MAX_SKILL_FILE_BYTES, SkillRegistry
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class SkillArgs(ToolArgsModel):
    skill_id: str = Field(..., min_length=1, description="Skill id from the catalog, e.g. 'bundled/orient-first'.")
    resource: str = Field(
        default="",
        description="Optional file inside the skill (a path listed under resources). Empty loads SKILL.md.",
    )


class SkillTool(WorkspaceTool):
    name = "skill"
    description = (
        "Load a skill when it applies to the task. The system prompt lists only skill ids and "
        "one-line descriptions; this returns the full SKILL.md instructions plus the skill's "
        "resource files. Pass resource to read one of those files."
    )
    args_model = SkillArgs

    def __init__(self, workspace: str | Path, *, registry: SkillRegistry) -> None:
        self.registry = registry
        super().__init__(workspace, parallel=True)

    def run(self, skill_id: str, resource: str = "") -> str:
        try:
            skill = self.registry.get(skill_id)
            path = self.registry.resource_path(skill_id, resource or "SKILL.md")
            if path.stat().st_size > MAX_SKILL_FILE_BYTES:
                return f"error: {resource or 'SKILL.md'} exceeds the {MAX_SKILL_FILE_BYTES} byte limit"
            text = path.read_text(encoding="utf-8").lstrip("\ufeff")
        except (OSError, UnicodeError, ValueError) as exc:
            return f"error: {exc}"
        if resource:
            return text
        header = [f"# skill {skill.skill_id}"]
        if skill.args:
            header.append(f"args: {render_args(skill.args)}")
        if skill.resources:
            header.append("resources: " + ", ".join(skill.resources))
        return "\n".join(header) + "\n\n" + text


__all__ = ["SkillArgs", "SkillTool"]
