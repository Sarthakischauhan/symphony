"""Approval policy is product rules, not TUI rendering."""

from pathlib import Path

from coding_agent.approvals import (
    ALLOW_ALWAYS,
    ALLOW_ONCE,
    DENY,
    ApprovalPolicy,
    child_control_plane,
)
from coding_agent.config import ApprovalConfig
from core_harness import EventControlPlane


def test_bash_and_overwrite_and_broad_patch_need_prompts(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    policy = ApprovalPolicy(tmp_path)
    config = ApprovalConfig()
    assert "ls" in policy.prompt_for(config, "bash", {"command": "ls"})
    assert "Overwrite" in policy.prompt_for(
        config, "write_file", {"path": "existing.txt"}
    )
    assert "Overwrite" in policy.prompt_for(
        config, "generate_image", {"path": "existing.txt", "prompt": "a cat"}
    )
    assert policy.prompt_for(config, "write_file", {"path": "new.txt"}) == ""
    assert policy.prompt_for(
        config,
        "patch",
        {"path": "existing.txt", "old_str": "x" * 500, "new_str": "y"},
    )
    assert (
        policy.prompt_for(
            config,
            "patch",
            {"path": "existing.txt", "old_str": "old", "new_str": "new"},
        )
        == ""
    )
    assert policy.prompt_for(config, "read_file", {"path": "existing.txt"}) == ""


def test_always_allow_mode_never_prompts(tmp_path: Path) -> None:
    policy = ApprovalPolicy(tmp_path)
    config = ApprovalConfig(mode="always_allow")
    assert policy.prompt_for(config, "bash", {"command": "rm -rf /"}) == ""
    allowed, promote = policy.interpret(config, DENY)
    assert allowed is True
    assert promote is False


def test_interpret_allow_once_always_and_deny(tmp_path: Path) -> None:
    policy = ApprovalPolicy(tmp_path)
    config = ApprovalConfig()
    assert policy.interpret(config, ALLOW_ONCE) == (True, False)
    assert policy.interpret(config, ALLOW_ALWAYS) == (True, True)
    assert policy.interpret(config, DENY) == (False, False)
    assert policy.interpret(config, "yes") == (True, False)
    assert policy.interpret(config, "") == (False, False)


def test_unattended_plane_does_not_fork() -> None:
    assert child_control_plane(EventControlPlane()) is None


def test_textual_plane_forks_always_allow_child(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualControlPlane

    parent = TextualControlPlane(workspace=tmp_path)
    child = child_control_plane(parent)
    assert child is not None
    assert child is not parent
    assert child.approvals.mode == "always_allow"
    assert parent.approvals.mode == "ask"
