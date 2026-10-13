"""Approval policy is product rules, not TUI rendering."""

from pathlib import Path

from coding_agent.addons.approvals import (
    ALLOW_ALWAYS,
    ALLOW_ONCE,
    DENY,
    ApprovalAddon,
    ApprovalPolicy,
)
from coding_agent.config import ApprovalConfig
from core_harness import EventSink


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


def test_approval_addon_skips_unattended_planes(tmp_path: Path) -> None:
    addon = ApprovalAddon(tmp_path, EventSink())
    assert addon.fork_for_child(None) is None


def test_approval_addon_does_not_inherit_onto_children(tmp_path: Path) -> None:
    from coding_agent.tui.runtime import TextualEventSink

    parent = TextualEventSink(workspace=tmp_path)
    addon = ApprovalAddon(tmp_path, parent, approvals=ApprovalConfig())
    assert addon.fork_for_child(None) is None
    assert addon.approvals.mode == "ask"


def test_always_allow_is_agent_state_for_any_client(tmp_path: Path) -> None:
    """Promotion lives on the add-on, so it works without the TUI's sink."""
    import asyncio

    from core_harness import HumanInteraction

    async def scenario() -> tuple[ApprovalAddon, EventSink]:
        sink = EventSink()
        sink.interaction = HumanInteraction(sink)
        addon = ApprovalAddon(tmp_path, sink, approvals=ApprovalConfig())
        first = asyncio.create_task(addon.before_tool(tool_name="bash", arguments={"command": "ls"}))
        await asyncio.sleep(0)
        (asked,) = [e.payload for e in sink.events if e.event_type == "question_asked"]
        sink.interaction.answer(asked["request_id"], ALLOW_ALWAYS)
        assert await first is None
        # No second question: the mode was promoted on the add-on.
        assert await addon.before_tool(tool_name="bash", arguments={"command": "pwd"}) is None
        return addon, sink

    addon, sink = asyncio.run(scenario())
    assert addon.approvals.mode == "always_allow"
    assert [e.event_type for e in sink.events] == ["question_asked", "config_changed"]
    assert sink.events[-1].payload == {"approvals": {"mode": "always_allow"}}
