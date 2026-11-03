"""``symphony skills|plugins`` in a shell, ``/skills|/plugins|/installed`` in stdio and the TUI."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from textual.widgets import Static

from coding_agent import CodingAgent, cli
from coding_agent.commands import plugins_cli, skills_cli
from coding_agent.commands.cli_support import Context
from coding_agent.protocols.stdio import commands as stdio_commands
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.screens.extensions import ExtensionsModal
from extension_fixtures import claude_marketplace, plugin_tree, write_skill
from scripted_registry import ScriptedRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def test_every_subcommand_is_registered_and_usage_errors_never_exit(workspace: Path, tmp_path: Path) -> None:
    context = Context(workspace, tmp_path)
    for parser in (skills_cli.build_parser(), plugins_cli.build_parser()):
        assert parser.format_help()
    for run, argv in ((skills_cli.run, ["bogus"]), (skills_cli.run, ["add"]), (plugins_cli.run, ["mode"]), (plugins_cli.run, ["marketplace"])):
        outcome = run(argv, context)
        assert not outcome.ok and outcome.text.startswith("error:") and "usage:" in outcome.text
    helped = plugins_cli.run(["--help"], context)
    assert helped.ok and {"add", "enable", "marketplace", "update"} <= set(helped.text.split())
    assert skills_cli.run([], context).text.startswith("usage:")


def test_shell_entry_points_print_and_return_exit_codes(workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(workspace)
    write_skill(tmp_path / "s" / "hello", "hello", "Say hello.")
    monkeypatch.setattr(sys, "argv", ["symphony", "skills", "add", str(tmp_path / "s" / "hello")])
    with pytest.raises(SystemExit) as done:
        cli.main()
    assert done.value.code == 0 and "Installed hello (user)" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["symphony", "skills", "list"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "hello" in capsys.readouterr().out
    assert plugins_cli.main(["remove", "ghost"]) == 1
    assert "no plugin named 'ghost'" in capsys.readouterr().err


def test_skills_list_shows_mode_tokens_origin_and_path(workspace: Path, tmp_path: Path) -> None:
    context = Context(workspace, tmp_path)
    write_skill(tmp_path / "s" / "hello", "hello", "Say hello.")
    skills_cli.run(["add", str(tmp_path / "s" / "hello")], context)
    skills_cli.run(["mode", "hello", "name-only"], context)
    listed = skills_cli.run(["list"], context).text
    lines = listed.splitlines()
    assert lines[0].startswith("Skills (10) · catalog ") and lines[0].endswith("/6000 tokens")
    assert lines[1].split() == ["NAME", "MODE", "TOKENS", "ORIGIN", "PATH"]
    row = next(line for line in lines if line.startswith("hello"))
    assert "name only" in row and "user" in row and row.rstrip().endswith("SKILL.md")
    skills_cli.run(["disable", "hello"], context)
    assert " off " in next(line for line in skills_cli.run(["list"], context).text.splitlines() if line.startswith("hello"))
    skills_cli.run(["mode", "hello", "default"], context)
    assert skills_cli.run(["remove", "hello"], context).changed


def test_plugin_commands_end_to_end_in_a_shell(workspace: Path, tmp_path: Path) -> None:
    context = Context(workspace, tmp_path)
    market = claude_marketplace(tmp_path / "market", "acme")
    assert "Added marketplace acme" in plugins_cli.run(["marketplace", "add", str(market)], context).text
    assert "acme" in plugins_cli.run(["marketplace", "list"], context).text
    assert "Installed demo 1.0.0: 1 skills" in plugins_cli.run(["add", "demo@acme"], context).text
    listed = plugins_cli.run(["list"], context).text
    assert listed.splitlines()[1].split() == ["NAME", "VERSION", "STATE", "SCOPE", "SKILLS", "PATH"]
    assert "enabled" in listed and "installed" in listed
    assert plugins_cli.run(["disable", "demo"], context).text == "Disabled demo"
    assert "disabled" in plugins_cli.run(["list"], context).text
    assert plugins_cli.run(["enable", "demo"], context).text == "Enabled demo"
    assert plugins_cli.run(["update"], context).text.startswith("demo@acme: 1.0.0 (unchanged)")
    assert plugins_cli.run(["marketplace", "update"], context).text.startswith("acme: updated")
    assert plugins_cli.run(["marketplace", "remove", "acme"], context).text == "Removed marketplace acme (1 installed plugins kept)"
    assert plugins_cli.run(["remove", "demo"], context).text == "Removed demo@acme"
    assert plugins_cli.run(["list"], context).text == "Plugins (0)"


def test_enable_and_disable_an_addon_from_the_command_line(workspace: Path, tmp_path: Path) -> None:
    from extension_fixtures import addon_plugin_tree

    context = Context(workspace, tmp_path)
    plugins_cli.run(["add", str(addon_plugin_tree(tmp_path / "coded"))], context)
    assert "addon loads while this plugin is enabled" in plugins_cli.run(["list"], context).text
    assert plugins_cli.run(["disable", "coded"], context).text == "Disabled coded"
    assert "plugin disabled" in plugins_cli.run(["list"], context).text
    assert plugins_cli.run(["enable", "coded"], context).text == "Enabled coded"


def test_slash_commands_in_stdio_change_the_running_agent(workspace: Path, tmp_path: Path) -> None:
    agent = CodingAgent(registry=ScriptedRegistry({}), model_id="fake:test", workspace=workspace)  # type: ignore[arg-type]
    write_skill(tmp_path / "s" / "fresh", "fresh", "A fresh skill.")
    reply = asyncio.run(stdio_commands.execute(agent, f"/skills add {tmp_path / 's' / 'fresh'}"))
    assert "Installed fresh (user)" in reply
    assert "- fresh: A fresh skill. (file: " in agent.harness.system_prompt
    asyncio.run(stdio_commands.execute(agent, "/skills disable fresh"))
    assert "- fresh:" not in agent.harness.system_prompt and "fresh (file:" not in agent.harness.system_prompt
    assert asyncio.run(stdio_commands.execute(agent, "/skills")).startswith("Skills (")
    plugin = plugin_tree(tmp_path / "plug", "plug")
    asyncio.run(stdio_commands.execute(agent, f"/plugins add {plugin}"))
    assert "plug:alpha" in agent.harness.system_prompt
    with pytest.raises(ValueError, match="no plugin named"):
        asyncio.run(stdio_commands.execute(agent, "/plugins remove ghost"))
    with pytest.raises(ValueError, match="No closing quotation"):
        asyncio.run(stdio_commands.execute(agent, '/skills add "oops'))
    names = {item["name"] for item in stdio_commands.catalog()}
    assert {"skills", "plugins", "installed"} <= names


def _texts(app: CodingAgentApp) -> list[str]:
    return [str(widget.render()) for widget in app.screen.query(Static)]


def test_tui_slash_commands_install_and_the_installed_screen_shows_cost_and_skipped(workspace: Path, tmp_path: Path) -> None:
    plugin = plugin_tree(tmp_path / "plug", "plug", skills=("alpha",))
    (plugin / "hooks").mkdir()
    write_skill(tmp_path / "s" / "hello", "hello", "Say hello.")
    app = CodingAgentApp(workspace=workspace)

    async def _run() -> list[str]:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await app._run_slash_command(f"/skills add {tmp_path / 's' / 'hello'}")
            await app._run_slash_command(f"/plugins add {plugin}")
            await pilot.pause()
            await app._run_slash_command("/installed")
            await pilot.pause()
            assert isinstance(app.screen, ExtensionsModal)
            return _texts(app)

    texts = asyncio.run(_run())
    joined = "\n".join(texts)
    assert any(text.startswith("SKILLS  ·  11  ·  catalog ") and text.endswith("of 6000 tokens") for text in texts)
    assert "ON · " in joined and " tok" in joined
    assert "hello" in texts and "plug:alpha" in texts
    assert "plug 1.0.0" in texts and "ENABLED" in texts
    assert "skipped  hooks: hooks are not supported; Symphony runs plugin code only as an addon" in texts
    assert "PLUGINS  ·  1" in texts


def test_tui_shows_a_failed_command_as_an_error_notice_not_an_exception(workspace: Path) -> None:
    app = CodingAgentApp(workspace=workspace)

    async def _run() -> list[str]:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await app._run_slash_command("/plugins add /does/not/exist")
            await pilot.pause()
            return [str(widget.render()) for widget in app.query(Static)]

    assert any("cannot read '/does/not/exist' as a source" in text for text in asyncio.run(_run()))
