"""User addons in the coding agent: discovery, merge, /reload, /addons."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from coding_agent import CodingAgent
from coding_agent.addons.manager import user_addons_root
from coding_agent.protocols.stdio import commands as stdio_commands

from scripted_registry import ScriptedRegistry

REPO = Path(__file__).resolve().parents[2]

ADDON = """
from core_harness import Tool
from core_harness.extensions import CommandSpec

def setup(api):
    for tool in {tools!r}:
        api.register_tool(Tool(lambda: "ok", name=tool, description="addon tool"))
    api.register_command(CommandSpec({command!r}, "addon command", lambda argument: "reply:" + argument))

def dispose():
    with open({log!r}, "a", encoding="utf-8") as handle:
        handle.write({name!r} + "\\n")
"""


@pytest.fixture()
def addons_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path / "symphony"))
    root = user_addons_root()
    root.mkdir(parents=True)
    return root


def _write(root: Path, name: str, tools: tuple[str, ...], command: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(exist_ok=True)
    log = root.parent / "disposed.log"
    (folder / "addon.py").write_text(
        ADDON.format(tools=tools, command=command or f"{name}_cmd", log=str(log), name=name),
        encoding="utf-8",
    )
    return log


def _agent(workspace: Path, registry: object | None = None) -> CodingAgent:
    return CodingAgent(registry=registry or ScriptedRegistry({}), model_id="fake:test", workspace=workspace)  # type: ignore[arg-type]


def test_user_addon_tools_and_commands_are_merged(addons_dir: Path, tmp_path: Path) -> None:
    _write(addons_dir, "alpha", ("alpha_tool",))
    agent = _agent(tmp_path / "ws")
    assert "alpha_tool" in agent.harness.tools
    assert agent.harness.tool_schemas()[-1]["name"] == "alpha_tool"
    assert [c.name for c in agent.user_addons.surface.slash_commands] == ["alpha_cmd"]
    names = {item["name"] for item in stdio_commands.catalog(extra=agent.user_addons.surface.slash_commands)}
    assert {"alpha_cmd", "addons"} <= names
    assert asyncio.run(stdio_commands.execute(agent, "/alpha_cmd hi")) == "reply:hi"


def test_reload_swap_adds_removes_and_disposes(addons_dir: Path, tmp_path: Path) -> None:
    log = _write(addons_dir, "alpha", ("alpha_tool", "shared_tool"))
    agent = _agent(tmp_path / "ws")
    assert agent.reload_user_addons() == "no tool changes"
    assert log.read_text(encoding="utf-8") == "alpha\n"
    _write(addons_dir, "alpha", ("shared_tool", "beta_tool", "gamma_tool"))
    assert agent.reload_user_addons() == "tools changed (+2/-1): prompt cache will rebuild"
    assert log.read_text(encoding="utf-8") == "alpha\nalpha\n"
    assert {"shared_tool", "beta_tool", "gamma_tool"} <= set(agent.harness.tools)
    assert "alpha_tool" not in agent.harness.tools
    assert sum(tool.name == "shared_tool" for tool in agent.tools) == 1


def test_builtin_name_collisions_are_rejected(addons_dir: Path, tmp_path: Path) -> None:
    _write(addons_dir, "persistence", ("x_tool",))
    _write(addons_dir, "clash", ("bash", "own_tool"), command="reload")
    agent = _agent(tmp_path / "ws")
    surface = agent.user_addons.surface
    assert [a.name for a in surface.snapshot.loaded] == ["clash"]
    assert surface.tool_names == {"own_tool"}
    assert surface.commands == ()
    assert agent.harness.tools["bash"] is not surface.snapshot.loaded[0].tools[0]
    joined = "\n".join(surface.notices)
    assert "'persistence' uses a built-in name" in joined
    assert "'bash' is already taken" in joined and "/reload is already taken" in joined


def test_reload_is_queued_during_a_run(addons_dir: Path, tmp_path: Path) -> None:
    _write(addons_dir, "alpha", ("alpha_tool",))
    agent = _agent(tmp_path / "ws", ScriptedRegistry({}, delay=0.2))
    _write(addons_dir, "alpha", ("beta_tool",))
    seen: list[dict] = []
    agent.sink.subscribe(lambda event, payload: seen.append(payload) if event == "config_changed" else None)

    async def scenario() -> str:
        run = asyncio.create_task(agent.run("hello"))
        await asyncio.sleep(0.05)
        queued = agent.reload_user_addons()
        assert "alpha_tool" in agent.harness.tools
        await run
        return queued

    assert "queued" in asyncio.run(scenario())
    assert "beta_tool" in agent.harness.tools and "alpha_tool" not in agent.harness.tools
    assert agent.user_addons.reload_pending is False
    assert seen[-1] == {"addons": "tools changed (+1/-1): prompt cache will rebuild"}


def test_prompt_prefix_is_stable_when_addons_are_unchanged(addons_dir: Path, tmp_path: Path) -> None:
    _write(addons_dir, "alpha", ("alpha_tool",))
    agent = _agent(tmp_path / "ws")
    before = (agent.harness.system_prompt, agent.harness.tool_schemas())
    agent.reload_user_addons()
    agent.apply_system_prompt()
    assert (agent.harness.system_prompt, agent.harness.tool_schemas()) == before


def test_addons_command_lists_loaded_and_failed(addons_dir: Path, tmp_path: Path) -> None:
    _write(addons_dir, "alpha", ("alpha_tool",))
    (addons_dir / "broken").mkdir()
    (addons_dir / "broken" / "addon.py").write_text("def setup(api):\n    raise KeyError('nope')\n")
    (addons_dir / "hooky").mkdir()
    (addons_dir / "hooky" / "addon.py").write_text(
        "def setup(api):\n    api.on('run_started', lambda event, payload: 1 / 0)\n"
    )
    agent = _agent(tmp_path / "ws")
    agent.user_addons.on_event("run_started", {})
    report = asyncio.run(stdio_commands.execute(agent, "/addons"))
    assert "alpha 0.0.0 · tools: alpha_tool · commands: /alpha_cmd" in report
    assert "broken · setup · KeyError: 'nope'" in report
    assert "hooky · hook · ZeroDivisionError" in report


def test_stdio_reload_reports_tool_changes(addons_dir: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path / "ws")
    _write(addons_dir, "alpha", ("alpha_tool",))
    reply = asyncio.run(stdio_commands.execute(agent, "/reload"))
    assert "tools changed (+1/-0)" in reply


def test_example_addon_from_docs_loads(addons_dir: Path, tmp_path: Path) -> None:
    shutil.copytree(REPO / "docs" / "addons" / "example", addons_dir / "example")
    agent = _agent(tmp_path / "ws")
    surface = agent.user_addons.surface
    assert surface.snapshot.failed == ()
    assert surface.tool_names == {"example_word_count"}
    assert asyncio.run(agent.harness.tools["example_word_count"].execute(sink=None, args={"text": "a b c"})) == "3"
    agent.user_addons.on_event("turn_completed", {})
    assert asyncio.run(stdio_commands.execute(agent, "/hello Sarthak")) == (
        "Hello, Sarthak! The example addon has seen 1 turns."
    )
    agent.dispose_user_addons()
    agent.user_addons.on_event("turn_completed", {})
    assert "seen 1 turns" in asyncio.run(stdio_commands.execute(agent, "/hello"))


def test_tui_reload_is_queued_while_busy_then_disposes_and_reports(
    addons_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from coding_agent.tui.app import CodingAgentApp

    log = _write(addons_dir, "alpha", ("alpha_tool",))
    workspace = tmp_path / "ws"
    old_agent = _agent(workspace)
    _write(addons_dir, "alpha", ("beta_tool", "gamma_tool"))
    new_registry = ScriptedRegistry({})
    new_registry.namespaces = lambda: ()  # type: ignore[attr-defined]
    new_agent = _agent(workspace, new_registry)
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr("coding_agent.tui.commands.manager.load_provider_env", lambda _workspace: None)
    monkeypatch.setattr("coding_agent.tui.commands.manager.build_agent", lambda **_kwargs: new_agent)
    app = CodingAgentApp(workspace=workspace)
    notices: list[str] = []

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent = old_agent
            monkeypatch.setattr(app, "add_notice", lambda text, tone="info": notices.append(text))
            app._busy = True
            await app._command_manager.run("/reload")
            assert app._reload_queued and app._agent is old_agent
            assert log.read_text(encoding="utf-8") == ""
            await app._command_manager.run("/addons")
            assert "alpha 0.0.0 · tools: alpha_tool" in notices[-1]
            app._busy = False
            app._reload_queued = False
            await app._command_manager.run("/reload")
            await pilot.pause()
            assert app._agent is new_agent, notices
            assert log.read_text(encoding="utf-8") == "alpha\n"
            assert "Addons: tools changed (+2/-1): prompt cache will rebuild" in notices

    asyncio.run(_run())
