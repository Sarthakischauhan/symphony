"""The start screen: what it shows, how it fits, and resuming a recent conversation from it."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult

from coding_agent.tui.transcript.welcome import LOGO, TIPS, RecentSession, Welcome, load_art

RECENT = tuple(
    RecentSession(f"session-{index}", f"Conversation number {index}", f"{index + 1}h ago") for index in range(5)
)


class _Host(App[None]):
    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self.requested: list[str] = []

    def compose(self) -> ComposeResult:
        yield Welcome(self.workspace)

    def on_welcome_resume_requested(self, message: Welcome.ResumeRequested) -> None:
        self.requested.append(message.session_id)


def _rows(welcome: Welcome) -> list[str]:
    return [welcome.render_line(y).text for y in range(welcome.size.height)]


def _text(app: App) -> str:
    return "\n".join(_rows(app.query_one(Welcome)))


def test_card_shows_logo_context_and_recent_conversations(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    app = _Host(tmp_path)

    async def run() -> None:
        async with app.run_test(size=(150, 40)) as pilot:
            welcome = app.query_one(Welcome)
            welcome.set_facts(replace(welcome.facts, skills=3, plugins=1, recent=RECENT))
            await pilot.pause()
            screen = _text(app)
            assert "███████╗" in screen
            assert "AGENTS.md" in screen and "3 skills" in screen and "1 plugin" in screen
            assert "click to open" in screen
            assert all(session.title in screen for session in RECENT)

    asyncio.run(run())


@pytest.mark.parametrize("size", [(150, 40), (120, 36), (90, 30), (64, 24), (100, 18), (60, 12)])
def test_card_always_fits_the_space_it_has(tmp_path: Path, size: tuple[int, int]) -> None:
    app = _Host(tmp_path)

    async def run() -> None:
        async with app.run_test(size=size) as pilot:
            welcome = app.query_one(Welcome)
            welcome.set_facts(replace(welcome.facts, skills=3, plugins=1, recent=RECENT))
            await pilot.pause()
            lines = app.console.render_lines(welcome.render(), app.console.options.update_width(welcome.size.width))
            assert len(lines) <= welcome.size.height
            screen = _text(app)
            # Whatever fits, the bottom border is never cut off.
            assert ("╰" in screen) == ("╭" in screen)

    asyncio.run(run())


def test_clicking_a_recent_conversation_asks_to_resume_it(tmp_path: Path) -> None:
    app = _Host(tmp_path)

    async def run() -> None:
        async with app.run_test(size=(90, 30)) as pilot:
            welcome = app.query_one(Welcome)
            welcome.set_facts(replace(welcome.facts, recent=RECENT))
            await pilot.pause()
            y, line = next((y, line) for y, line in enumerate(_rows(welcome)) if "Conversation number 2" in line)
            await pilot.click(Welcome, offset=(line.index("Conversation number 2") + 2, y))
            await pilot.pause()
            assert app.requested == ["session-2"]

    asyncio.run(run())


def test_tips_put_workspace_advice_first(tmp_path: Path) -> None:
    welcome = Welcome(tmp_path)
    assert welcome.tips()[0][0] == "AGENTS.md"
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    welcome = Welcome(tmp_path)
    assert welcome.tips() == list(TIPS)
    welcome.facts = replace(welcome.facts, recent=RECENT[:1])
    assert welcome.tips()[0][0] == "click"


def test_tip_rotates(tmp_path: Path) -> None:
    app = _Host(tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 36)) as pilot:
            welcome = app.query_one(Welcome)
            first = welcome.current_tip()
            welcome._next_tip()
            await pilot.pause()
            assert welcome.current_tip() != first

    asyncio.run(run())


def test_dashboard_art_still_replaces_the_logo(tmp_path: Path) -> None:
    assert load_art(tmp_path) == list(LOGO)
    (tmp_path / "dashboard.toml").write_text('title = "x"\n', encoding="utf-8")
    assert load_art(tmp_path) == list(LOGO)
    (tmp_path / "dashboard.toml").write_text('art = ["hi"]\n', encoding="utf-8")
    assert load_art(tmp_path) == ["hi"]
    (tmp_path / "dashboard.toml").write_text("art = 3\n", encoding="utf-8")
    assert load_art(tmp_path) == []


# --- resuming in place ------------------------------------------------------


class _Harness:
    model_id = "openai:test"

    def __init__(self) -> None:
        self.shut_down = False

    async def shutdown_children(self) -> None:
        self.shut_down = True

    def drain_child_results(self) -> None:
        pass


class _Agent:
    def __init__(self) -> None:
        self.session_id = "current"
        self.harness = _Harness()

    def bind_session(self, session_id: str) -> None:
        self.session_id = session_id


class _App:
    def __init__(self, workspace: Path, *, busy: bool = False) -> None:
        self._agent = _Agent()
        self._busy = busy
        self.workspace = workspace
        self.session_id = "current"
        self._ui_state = SimpleNamespace(model_id="")
        self.notices: list[tuple[str, str]] = []
        self.calls: list[str] = []
        self.prompt = SimpleNamespace(focus=lambda: self.calls.append("focus"))

    def add_notice(self, text: str, level: str = "info") -> None:
        self.notices.append((text, level))

    def action_clear_transcript(self) -> None:
        self.calls.append("clear")

    def load_session_history(self) -> None:
        # The real method is a Textual @work worker: calling it starts the load.
        self.calls.append(f"history:{self._agent.session_id}")

    def query_one(self, selector: str):
        assert selector == "#prompt"
        return self.prompt


def _claims(monkeypatch: pytest.MonkeyPatch, *, refuse: bool = False) -> list[str]:
    claimed: list[str] = []

    def register(session_id: str, **_: object) -> None:
        if refuse:
            raise RuntimeError("owned elsewhere")
        claimed.append(session_id)

    monkeypatch.setattr("coding_agent.addons.persistence.active.register_active", register)
    return claimed


def test_resume_binds_the_session_and_loads_its_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from coding_agent.tui.commands.manager import resume_session

    claimed = _claims(monkeypatch)
    app = _App(tmp_path)
    asyncio.run(resume_session(app, "older"))

    assert claimed == ["older"]
    assert app._agent.harness.shut_down
    assert app.session_id == app._agent.session_id == "older"
    assert app.calls == ["clear", "history:older", "focus"]
    assert app.notices == []


def test_resume_leaves_everything_alone_when_another_window_owns_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from coding_agent.tui.commands.manager import resume_session

    _claims(monkeypatch, refuse=True)
    app = _App(tmp_path)
    asyncio.run(resume_session(app, "older"))

    assert app._agent.session_id == "current"
    assert not app._agent.harness.shut_down
    assert app.calls == []
    assert app.notices and "another Symphony window" in app.notices[0][0]


def test_resume_waits_for_a_running_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from coding_agent.tui.commands.manager import resume_session

    claimed = _claims(monkeypatch)
    app = _App(tmp_path, busy=True)
    asyncio.run(resume_session(app, "older"))

    assert claimed == []
    assert app._agent.session_id == "current"
    assert app.notices[0][1] == "warning"
