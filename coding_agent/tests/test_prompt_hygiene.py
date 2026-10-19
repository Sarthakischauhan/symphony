"""Git/commit hygiene in prompts and tool descriptions; ask_user never defaults to a bypass."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core_harness import EventSink, InteractionPort

from coding_agent.config.prompts import SUBAGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from coding_agent.tools.ask_user import AskUserTool, demote_verification_bypass
from coding_agent.tools.bash import BashTool
from coding_agent.tools.write_file import WriteFileTool


class RecordingInteraction(InteractionPort):
    def __init__(self, answer: str = "") -> None:
        super().__init__()
        self.answer = answer
        self.calls: list[tuple[list[str], str]] = []

    async def request_user_input(self, *, question: str, choices: list[str], default: str, **kwargs: object) -> str:
        self.calls.append((choices, default))
        return self.answer


def test_bash_description_appends_git_rules_after_existing_text() -> None:
    description = BashTool.description
    # Existing text is unchanged and stays first, so the cached tool schema prefix is stable.
    assert description.startswith("Run a shell command (bash) in the working directory")
    existing_end = description.index("killed as a group according to the configured limits.")
    git = description.index("Git: commit only when the user asks.")
    assert existing_end < git
    for rule in ("git status", "git diff", "stage files by name", "never git add -A",
                 "*.tgz", "node_modules", "screenshots or images", "secrets", "--no-verify", "force-push"):
        assert rule in description


def test_write_file_prefers_patch_and_no_unrequested_docs() -> None:
    description = WriteFileTool.description
    assert description.startswith("Create or overwrite a UTF-8 text file while preserving content exactly")
    assert "Prefer patch for changing existing files." in description
    assert "Never create docs (*.md, README) or notes unless asked" in description


def test_system_prompts_carry_edit_first_and_commit_rules_in_place() -> None:
    implementation = SYSTEM_PROMPT.index("Implementation:")
    verification = SYSTEM_PROMPT.index("Verification:")
    for rule in ("Prefer editing existing files to creating new ones.", "Commit only when asked."):
        assert implementation < SYSTEM_PROMPT.index(rule) < verification
    assert "Do not commit, push, or create docs or assets" in SUBAGENT_SYSTEM_PROMPT
    # The prompts are constant: nothing per-run (dates, paths) leaks into the cached prefix.
    assert "{" not in SUBAGENT_SYSTEM_PROMPT


def test_bypass_is_never_default_or_first() -> None:
    choices, default = demote_verification_bypass(
        ["Bypass the hook with --no-verify", "Fix the lint errors", "Stop"],
        "Bypass the hook with --no-verify",
    )
    assert choices == ["Fix the lint errors", "Stop", "Bypass the hook with --no-verify"]
    assert default == ""
    assert demote_verification_bypass(["Skip the pre-commit hook", "Run tests again"], "Run tests again") == (
        ["Run tests again", "Skip the pre-commit hook"],
        "Run tests again",
    )
    # Only bypass presets: offer none, so nothing is preselected.
    assert demote_verification_bypass(["git commit --no-verify", "Disable the CI check"], "") == ([], "")
    # Ordinary answers are untouched.
    assert demote_verification_bypass(["Yes", "No"], "Yes") == (["Yes", "No"], "Yes")


def test_ask_user_sends_demoted_choices_to_the_human(tmp_path: Path) -> None:
    interaction = RecordingInteraction()
    tool = AskUserTool(str(tmp_path))
    answer = asyncio.run(
        tool.run(
            "The pre-commit hook failed. How should I proceed?",
            choices=["Bypass the hook", "Fix the failure"],
            default="Bypass the hook",
            sink=EventSink(interaction),
        )
    )
    assert interaction.calls == [(["Fix the failure", "Bypass the hook"], "")]
    # An empty answer no longer falls back to the bypass default.
    assert answer == ""


def test_unattended_ask_user_never_hints_a_bypass(tmp_path: Path) -> None:
    tool = AskUserTool(str(tmp_path), unattended=True)
    result = asyncio.run(
        tool.run("Hook failed", choices=["skip hooks (--no-verify)", "Fix it"], default="skip hooks (--no-verify)")
    )
    assert "no-verify" not in result
    assert "choices: Fix it" in result
    assert "default:" not in result
