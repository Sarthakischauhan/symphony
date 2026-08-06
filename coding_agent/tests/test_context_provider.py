"""Cached repository context provider tests."""

from __future__ import annotations

from pathlib import Path

from coding_agent.context import RepositoryContextProvider


def _write_tree(root: Path, n: int = 40) -> None:
    for i in range(n):
        package = root / f"pkg{i % 5}"
        package.mkdir(exist_ok=True)
        (package / f"mod{i}.py").write_text(
            f'"""mod {i}."""\n'
            f"from helper import util as u\n\n"
            f"MAX_{i} = {i}\n\n"
            f"class C{i}:\n"
            f"    def run(self):\n"
            f"        self.helper()\n"
            f"        u()\n"
            f"    def helper(self):\n"
            f"        return {i}\n\n"
            f"def outer():\n"
            f"    def inner():\n"
            f"        return C{i}().run()\n"
            f"    return inner()\n",
            encoding="utf-8",
        )
    (root / "helper.py").write_text("def util():\n    return 1\n", encoding="utf-8")


def test_provider_caches_and_invalidates_changed_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    provider = RepositoryContextProvider(tmp_path)
    provider.refresh()
    first_parses = provider.parse_count
    provider.refresh()
    assert provider.parse_count == first_parses  # unchanged files not reparsed

    (tmp_path / "a.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    provider.refresh()
    assert provider.parse_count == first_parses + 1

    provider.invalidate("a.py")
    provider.refresh()
    assert provider.parse_count == first_parses + 2


def test_repo_map_is_token_budgeted(tmp_path: Path) -> None:
    _write_tree(tmp_path, n=60)
    provider = RepositoryContextProvider(tmp_path, max_map_chars=1200)
    repo_map = provider.repo_map()
    assert len(repo_map) <= 1200
    assert "Repository map:" in repo_map


def test_on_demand_queries_and_self_method_attribution(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "class Runner:\n"
        "    def run(self):\n"
        "        self.helper()\n"
        "    def helper(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    provider = RepositoryContextProvider(tmp_path)
    callees = provider.query(action="callees", name="Runner.run")
    assert "Runner.helper" in callees or "helper" in callees
    found = provider.query(action="find", name="helper")
    assert "m.py:Runner.helper" in found


def test_duplicate_names_listed_separately(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def shared():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def shared():\n    return 2\n", encoding="utf-8")
    provider = RepositoryContextProvider(tmp_path)
    found = provider.query(action="find", name="shared")
    assert "a.py:shared" in found and "b.py:shared" in found
    assert "Duplicate short names" in found


def test_import_alias_and_nested_functions(tmp_path: Path) -> None:
    (tmp_path / "lib.py").write_text("def util():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from lib import util as u\n"
        "def outer():\n"
        "    def inner():\n"
        "        return u()\n"
        "    return inner()\n",
        encoding="utf-8",
    )
    provider = RepositoryContextProvider(tmp_path)
    found = provider.query(action="find", name="inner")
    assert "app.py:outer.inner" in found
    callees = provider.query(action="callees", name="outer.inner")
    assert "util" in callees or "lib.util" in callees


def test_constant_line_numbers(tmp_path: Path) -> None:
    (tmp_path / "c.py").write_text("\n\nMAX_SIZE = 10\n", encoding="utf-8")
    provider = RepositoryContextProvider(tmp_path)
    found = provider.query(action="find", name="MAX_SIZE")
    assert "c.py:3" in found


def test_unreadable_and_parse_errors_are_graceful(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def (\n", encoding="utf-8")
    provider = RepositoryContextProvider(tmp_path)
    summary = provider.summary()
    assert any(module.errors for module in summary.modules)
    # Should not raise
    provider.repo_map()


def test_performance_budget_on_realistic_repo(tmp_path: Path) -> None:
    _write_tree(tmp_path, n=80)
    provider = RepositoryContextProvider(tmp_path, max_map_chars=2000)
    provider.refresh()
    parses_after_build = provider.parse_count
    # Repeated queries must not reparse the whole tree.
    for _ in range(10):
        provider.query(action="find", name="run")
        provider.repo_map()
    assert provider.parse_count == parses_after_build
    assert len(provider.repo_map()) <= 2000
