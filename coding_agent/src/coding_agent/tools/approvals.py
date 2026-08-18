"""Ask before bash, overwriting files, or applying a broad patch."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, List, Sequence

from core_harness import Tool

ALLOW_ANSWERS = {"y", "yes", "allow", "allow once", "a"}
BROAD_PATCH_CHARS = 400


class ApprovalTool:
    """Wrap a harness tool and optionally prompt before executing it."""

    def __init__(self, inner: Tool, workspace: Path) -> None:
        self.inner = inner
        self.workspace = Path(workspace).resolve()
        self.name = inner.name
        self.description = inner.description
        self.parameters = getattr(inner, "parameters", None)

    def get_schema(self) -> dict[str, Any]:
        return self.inner.get_schema()

    async def execute(self, *, control_plane: Any, args: dict[str, Any]) -> Any:
        needed, prompt = approval_prompt(self.name, args, self.workspace)
        if needed:
            allowed = await request_approval(control_plane, prompt)
            if not allowed:
                return "error: tool call denied by user"
        return await self.inner.execute(control_plane=control_plane, args=args)


def wrap_with_approvals(tools: Sequence[Tool], workspace: Path) -> List[Tool]:
    return [ApprovalTool(tool, workspace) for tool in tools]  # type: ignore[misc]


def approval_prompt(name: str, args: dict[str, Any], workspace: Path) -> tuple[bool, str]:
    if name == "bash":
        command = str(args.get("command") or "").strip()
        return True, f"Allow bash command once?\n`{command}`"
    if name == "write_file":
        path = str(args.get("path") or "").strip()
        if path and _exists_in_workspace(workspace, path):
            return True, f"Overwrite existing file `{path}`?"
        return False, ""
    if name == "patch":
        path = str(args.get("path") or "").strip()
        old_str = str(args.get("old_str") or args.get("old_string") or "")
        replace_all = bool(args.get("replace_all"))
        if replace_all or len(old_str) > BROAD_PATCH_CHARS:
            kind = "global" if replace_all else "large"
            return True, f"Apply a {kind} patch to `{path}`?"
        return False, ""
    return False, ""


def _exists_in_workspace(workspace: Path, path: str) -> bool:
    try:
        target = (workspace / path).resolve()
        return target.is_relative_to(workspace.resolve()) and target.exists()
    except OSError:
        return False


async def request_approval(control_plane: Any, prompt: str) -> bool:
    ask = getattr(control_plane, "ask_user", None)
    if not callable(ask):
        return True
    request_id = uuid.uuid4().hex
    emit = getattr(control_plane, "emit", None)
    if callable(emit):
        await emit(
            "question_asked",
            {
                "request_id": request_id,
                "question": f"{prompt}\nAllow once or Deny.",
                "choices": ["Allow once", "Deny"],
                "default": "Deny",
            },
        )
    answer = str(await ask(request_id) or "").strip()
    return answer.lower() in ALLOW_ANSWERS


def is_allow_answer(answer: str) -> bool:
    return str(answer or "").strip().lower() in ALLOW_ANSWERS


__all__ = [
    "ALLOW_ANSWERS",
    "ApprovalTool",
    "approval_prompt",
    "is_allow_answer",
    "request_approval",
    "wrap_with_approvals",
]
