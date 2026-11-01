"""One root order for skills and plugins: project, user, ~/.agents, bundled."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config import symphony_dir
from coding_agent.extensions import BUNDLED_SKILLS, extension_roots


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path / "symphony-home"))
    return tmp_path / "home"


def test_order_is_nearest_project_dirs_then_user_then_agents_then_bundled(tmp_path: Path, home: Path) -> None:
    repo = tmp_path / "repo"
    workspace = repo / "packages" / "app"
    workspace.mkdir(parents=True)
    (repo / ".git").mkdir()
    roots = extension_roots(workspace)
    assert [(root.scope, root.skills) for root in roots] == [
        ("project", workspace.resolve() / ".symphony" / "skills"),
        ("project", workspace.resolve() / ".agents" / "skills"),
        ("project", (repo / "packages" / ".symphony" / "skills").resolve()),
        ("project", (repo / "packages" / ".agents" / "skills").resolve()),
        ("project", repo.resolve() / ".symphony" / "skills"),
        ("project", repo.resolve() / ".agents" / "skills"),
        ("user", tmp_path.resolve() / "symphony-home" / "skills"),
        ("agents", home.resolve() / ".agents" / "skills"),
        ("bundled", BUNDLED_SKILLS),
    ]
    assert roots[0].plugins == workspace.resolve() / ".symphony" / "plugins"
    assert roots[-1].plugins is None


def test_symphony_home_is_respected_not_the_process_home(tmp_path: Path, home: Path) -> None:
    user = next(root for root in extension_roots(tmp_path) if root.scope == "user")
    assert user.skills == symphony_dir() / "skills" == tmp_path.resolve() / "symphony-home" / "skills"
    assert user.plugins == symphony_dir() / "plugins"


def test_outside_a_git_repo_only_the_workspace_is_searched(tmp_path: Path, home: Path) -> None:
    workspace = tmp_path / "loose" / "dir"
    workspace.mkdir(parents=True)
    projects = [root for root in extension_roots(workspace) if root.scope == "project"]
    assert len(projects) == 2


def test_a_workspace_at_home_does_not_list_user_roots_twice(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home.mkdir(parents=True)
    monkeypatch.setenv("SYMPHONY_HOME", str(home / ".symphony"))
    scopes = [root.scope for root in extension_roots(home)]
    assert scopes == ["user", "agents", "bundled"]
