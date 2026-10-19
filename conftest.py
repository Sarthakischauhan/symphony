"""Hermetic environment shared by every package's tests.

Each test gets an empty HOME and SYMPHONY_HOME under its own tmp dir, and no
provider, model, auth, or tracing variable from the developer's shell (``uv
run`` can also load ``~/.env``), nor a ``GIT_*`` variable exported by a git
hook. Nothing reads the real ``~/.symphony`` config, OAuth tokens, or keys, so
a local setup cannot change which provider or model a test sees. Worker
subprocesses inherit this env.

The XDG and uv tool directories point into that tmp dir too, the startup
update check is off, and ``apply_update`` fails the test that calls it, so no
test can install over the developer's ``symphony``. As a backstop the session
records the real ``symphony`` executable, uv tool directory and Symphony home
before any test runs and fails if any of them changed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from coding_agent import updates
from coding_agent.config import symphony_dir
from core_ai.providers.catalog import PROVIDERS

REPO = Path(__file__).resolve().parent

_ENV_NAMES = (
    "SYMPHONY_HOME",
    "SYMPHONY_MODEL",
    "SYMPHONY_JEV_PROVIDER",
    "SYMPHONY_BROWSER_TEXT_MODEL",
    "JEV_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
    "OPENROUTER_MODEL",
    "OPENROUTER_DECISIONS_URL",
    "VERCEL_MODEL",
    "AI_GATEWAY_MODEL",
    "OLLAMA_MODEL",
    "LOCAL_MODEL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


def _provider_env_names() -> set[str]:
    names = set(_ENV_NAMES)
    for spec in PROVIDERS:
        names.update(name for name in (spec.env_key, *spec.env_aliases) if name)
        names.update(name for name in (spec.base_url_env, spec.host_env, spec.enabled_env) if name)
        names.add(f"SYMPHONY_{spec.id.upper()}_AUTH")
    return names


PROVIDER_ENV = frozenset(_provider_env_names())


def _playwright_browsers() -> str:
    """Playwright's browser cache under the real home, resolved before HOME is swapped."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if configured:
        return configured
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Caches" / "ms-playwright")
    if sys.platform == "win32":
        return str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright")


PLAYWRIGHT_BROWSERS = _playwright_browsers()


@pytest.fixture(autouse=True)
def hermetic_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME and SYMPHONY_HOME at a fresh tmp dir and drop provider env."""
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    # A git hook exports GIT_DIR/GIT_INDEX_FILE. Left in place, a test that runs
    # `git init && git commit` in its tmp dir writes into the outer repository.
    for name in [key for key in os.environ if key.startswith("GIT_") and key != "GIT_EXEC_PATH"]:
        monkeypatch.delenv(name)
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SYMPHONY_HOME", str(home / ".symphony"))
    # Browsers are a download cache, not user config: keep finding them.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", PLAYWRIGHT_BROWSERS)
    for name in ("XDG_BIN_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(name, str(home / "xdg" / name.removeprefix("XDG_").lower()))
    monkeypatch.setenv("UV_TOOL_DIR", str(home / "uv" / "tools"))
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(home / "uv" / "bin"))
    monkeypatch.setenv("SYMPHONY_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(updates, "apply_update", _refuse_update)
    return home


def _refuse_update(target: str) -> subprocess.CompletedProcess[str]:
    pytest.fail(f"a test tried to install symphony-code {target} for real")


# The real install, recorded per path as (mtime_ns, size, symlink target).
Stamp = tuple[int, int, str]
INSTALL_BEFORE = pytest.StashKey[tuple[list[Path], dict[str, Stamp]]]()


def _uv_tool_dir(*flags: str) -> Path | None:
    """``uv tool dir`` in the developer's own environment."""
    try:
        found = subprocess.run(["uv", "tool", "dir", *flags], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    path = found.stdout.strip()
    return Path(path) if found.returncode == 0 and path else None


def _stamp(path: Path) -> Stamp:
    info = path.lstat()
    return info.st_mtime_ns, info.st_size, os.readlink(path) if path.is_symlink() else ""


def _snapshot(roots: list[Path]) -> dict[str, Stamp]:
    stamps: dict[str, Stamp] = {}
    for root in roots:
        if not root.exists() and not root.is_symlink():
            continue
        stamps[str(root)] = _stamp(root)
        if root.is_dir() and not root.is_symlink():
            for directory, names, files in os.walk(root):
                for name in (*names, *files):
                    stamps[os.path.join(directory, name)] = _stamp(Path(directory, name))
    return stamps


def pytest_sessionstart(session: pytest.Session) -> None:
    """Record the real install before any test swaps HOME or the uv dirs."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return  # The controlling process guards the whole run.
    roots = [symphony_dir()]
    tools = _uv_tool_dir()
    if tools is not None:
        roots.append(tools)
    bin_dir = _uv_tool_dir("--bin")
    commands = [bin_dir / "symphony"] if bin_dir is not None else []
    on_path = shutil.which("symphony")
    # A `uv run` PATH finds the checkout's own .venv first; that is not the install.
    if on_path and not Path(on_path).resolve().is_relative_to(REPO):
        commands.append(Path(on_path))
    roots += commands
    session.stash[INSTALL_BEFORE] = (roots, _snapshot(roots))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run if the real symphony, uv tool dir or Symphony home changed."""
    if INSTALL_BEFORE not in session.stash:
        return
    roots, before = session.stash[INSTALL_BEFORE]
    after = _snapshot(roots)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    if not changed:
        return
    shown = "\n  ".join(changed[:20])
    more = f"\n  ... and {len(changed) - 20} more" if len(changed) > 20 else ""
    sys.stderr.write(f"\nThe test run changed the real Symphony install:\n  {shown}{more}\n")
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
