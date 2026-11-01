"""Reading a source string, and staging a path or git repository without running anything."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.extensions import source as sources
from coding_agent.extensions.source import GITHUB_BASE, Source, parse_source, stage
from extension_fixtures import commit_all, git, write_skill


def test_forms_of_a_source(tmp_path: Path) -> None:
    (tmp_path / "here").mkdir()
    assert parse_source("here", cwd=tmp_path) == Source("local", str((tmp_path / "here").resolve()))
    assert parse_source("https://github.com/o/r@v1", cwd=tmp_path) == Source("git", "https://github.com/o/r", "v1")
    assert parse_source("git@github.com:o/r.git", cwd=tmp_path) == Source("git", "git@github.com:o/r.git")
    assert parse_source("o/r", cwd=tmp_path) == Source("git", f"{GITHUB_BASE}o/r.git")
    assert parse_source("o/r@main", cwd=tmp_path) == Source("git", f"{GITHUB_BASE}o/r.git", "main")
    assert parse_source("plug@market", cwd=tmp_path) == Source("marketplace", "plug", marketplace="market")
    assert parse_source("o/r", cwd=tmp_path, subdir="skills/x").subdir == "skills/x"


def test_an_existing_path_beats_the_other_readings(tmp_path: Path) -> None:
    (tmp_path / "o" / "r").mkdir(parents=True)
    assert parse_source("o/r", cwd=tmp_path).kind == "local"
    (tmp_path / "a@b").mkdir()
    assert parse_source("a@b", cwd=tmp_path).kind == "local"


def test_marketplace_form_is_refused_where_it_makes_no_sense(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read"):
        parse_source("plug@market", cwd=tmp_path, marketplaces=False)
    with pytest.raises(ValueError, match="source is required"):
        parse_source("  ", cwd=tmp_path)


def test_local_staging_copies_files_but_not_symlinks_or_git(tmp_path: Path) -> None:
    root = tmp_path / "src"
    write_skill(root / "a", "a")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x")
    (tmp_path / "secret").write_text("secret")
    (root / "link").symlink_to(tmp_path / "secret")
    (root / "linked-dir").symlink_to(tmp_path)
    revision = stage(Source("local", str(root)), tmp_path / "out")
    assert revision == ""
    assert sorted(path.name for path in (tmp_path / "out").rglob("*") if path.is_file()) == ["SKILL.md"]


def test_staging_refuses_a_subdirectory_that_leaves_the_source(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    for subdir in ("..", "/etc", "missing"):
        with pytest.raises(ValueError, match="subdirectory"):
            stage(Source("local", str(tmp_path / "src"), subdir=subdir), tmp_path / "out")


def test_staging_a_size_over_the_cap_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "big").write_bytes(b"x" * 100)
    monkeypatch.setattr(sources, "MAX_STAGED_BYTES", 10)
    with pytest.raises(ValueError, match="larger than"):
        stage(Source("local", str(tmp_path / "src")), tmp_path / "out")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    write_skill(root / "one", "one")
    first = commit_all(root, "first")
    git(root, "tag", "v1")
    write_skill(root / "two", "two")
    second = commit_all(root, "second")
    return root, first, second


def test_git_staging_uses_the_default_branch_a_tag_or_a_sha(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    root, first, second = repo
    url = root.as_uri()
    assert stage(Source("git", url), tmp_path / "head") == second
    assert (tmp_path / "head" / "two" / "SKILL.md").is_file()
    assert stage(Source("git", url, "v1"), tmp_path / "tag") == first
    assert not (tmp_path / "tag" / "two").exists()
    assert stage(Source("git", url), tmp_path / "sha", sha=first[:12]) == first
    assert not (tmp_path / "sha" / ".git").exists()


def test_git_staging_errors_are_plain_messages(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    root, first, _ = repo
    with pytest.raises(ValueError, match="not a branch, tag or commit"):
        stage(Source("git", root.as_uri(), "nope"), tmp_path / "a")
    with pytest.raises(ValueError, match="git clone failed"):
        stage(Source("git", (tmp_path / "missing").as_uri()), tmp_path / "b")
    with pytest.raises(ValueError, match="not a branch, tag or commit"):
        stage(Source("git", root.as_uri()), tmp_path / "c", sha="deadbeef")
    with pytest.raises(ValueError, match="expected commit"):
        stage(Source("git", root.as_uri()), tmp_path / "d", sha="main")


def test_git_staging_of_a_subdirectory(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    root, _, _ = repo
    stage(Source("git", root.as_uri(), subdir="two"), tmp_path / "out")
    assert (tmp_path / "out" / "SKILL.md").is_file()
