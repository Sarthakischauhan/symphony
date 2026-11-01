"""The /installed screen: skill state and cost, plugin state, skipped parts and notices."""

import asyncio
from pathlib import Path

from textual.app import App
from textual.widgets import Static

from coding_agent.addons.plugins import ResolvedPlugin
from coding_agent.addons.skills import Skill, build_catalog
from coding_agent.addons.skills.args import ExtensionArg
from coding_agent.extensions import Diagnostic
from coding_agent.tui.screens.extensions import ExtensionsModal
from coding_agent.tui.screens.modal import EmptyState


def _plugin(base: Path, name: str, **fields: object) -> ResolvedPlugin:
    values: dict[str, object] = {
        "key": f"{name}@direct", "name": name, "version": "", "description": "", "root": base / name, "scope": "installed",
        "enabled": True, "skill_dirs": (), "skill_count": 0, "addon_root": None, "trust": "none", "skipped": (),
    }
    return ResolvedPlugin(**{**values, **fields})  # type: ignore[arg-type]


def _texts(modal: ExtensionsModal) -> list[str]:
    async def _run() -> list[str]:
        app = App()
        async with app.run_test(size=(120, 50)) as pilot:
            app.push_screen(modal)
            await pilot.pause()
            return [str(widget.render()) for widget in app.screen.query(Static)]

    return asyncio.run(_run())


def test_skill_cards_show_state_cost_args_and_path(tmp_path: Path) -> None:
    depth = ExtensionArg(name="depth", type="enum", enum=["sketch", "thorough"], description="D.", default="sketch")
    skills = (
        Skill("orient", "Map owners first.", tmp_path / "orient" / "SKILL.md", "user", args=(depth,)),
        Skill("quiet", "Only when asked.", tmp_path / "quiet" / "SKILL.md", "user", invocation="manual"),
        Skill("gone", "Disabled one.", tmp_path / "gone" / "SKILL.md", "user"),
    )
    catalog = build_catalog(skills, settings={}, disabled=frozenset({"gone"}), max_tokens=500)
    texts = _texts(ExtensionsModal(catalog, (), budget=500))
    assert "args  depth: enum[sketch|thorough]=sketch" in texts
    assert f"SKILL.md  {tmp_path / 'orient' / 'SKILL.md'}" in texts
    assert f"SKILLS  ·  3  ·  catalog {catalog.tokens} of 500 tokens" in texts
    states = [text for text in texts if text.startswith(("ON", "MANUAL", "OFF"))]
    assert any(text.startswith("ON · ") for text in states) and "MANUAL" in states and "OFF" in states
    assert "3 total" in texts


def test_plugin_cards_show_enabled_trust_skipped_parts_and_notices(tmp_path: Path) -> None:
    plugins = (
        _plugin(tmp_path, "search", version="1.2", description="Search before opening files.",
                skipped=(("hooks", "hooks are not supported"),)),
        _plugin(tmp_path, "idle", enabled=False, trust="untrusted", addon_root=tmp_path / "idle" / "addons"),
    )
    notices = (Diagnostic("/p/bad", "name: invalid"), Diagnostic("dup", "shadowed", "notice"))
    texts = _texts(ExtensionsModal(build_catalog((), settings={}, max_tokens=100), plugins, notices))
    assert {"search 1.2", "ENABLED", "Search before opening files.", "idle", "DISABLED"} <= set(texts)
    assert "skipped  hooks: hooks are not supported" in texts
    assert "addon not loaded: untrusted (run: symphony plugins trust idle)" in texts
    assert "error  /p/bad: name: invalid" in texts and "notice  dup: shadowed" in texts
    assert "NOTICES  ·  2" in texts and "PLUGINS  ·  2" in texts


def test_markup_like_names_and_paths_render_literally(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "odd[/]id", root=tmp_path / "odd[/]root")
    texts = _texts(ExtensionsModal(build_catalog((), settings={}, max_tokens=100), (plugin,)))
    assert "odd[/]id" in texts and str(tmp_path / "odd[/]root") in texts


def test_an_empty_screen_shows_the_empty_state() -> None:
    async def _run() -> int:
        app = App()
        async with app.run_test(size=(120, 50)) as pilot:
            app.push_screen(ExtensionsModal(build_catalog((), settings={}, max_tokens=100), ()))
            await pilot.pause()
            return len(app.screen.query(EmptyState))

    assert asyncio.run(_run()) == 1
