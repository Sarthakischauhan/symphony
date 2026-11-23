"""``symphony doctor``: check the Symphony install and repair what can be repaired.

Checks only read. A fix changes files in the Symphony home (``~/.symphony``)
and moves aside, never deletes, anything a user wrote: a broken
``config.json`` or ``theme.toml`` is renamed with a ``.broken-<time>`` suffix
before defaults take its place. The one fix outside the home is the update,
which runs the same ``uv tool install`` as ``symphony update``.

Nothing here loads the TUI or runs plugin, skill or addon code. Extension
problems are found by reading files, the way ``symphony plugins list`` does.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal, Sequence

Status = Literal["ok", "info", "warn", "fail"]

# Leftover atomic-write temp files are only removed once nobody can still be writing them.
STALE_TEMP_SECONDS = 3600
# A few lock files are normal; the doctor offers to tidy them once they pile up.
UNUSED_LOCKS_WORTH_CLEANING = 50


@dataclass(frozen=True)
class Fix:
    """A repair the doctor can make. ``apply`` returns one line saying what it did."""

    summary: str
    apply: Callable[[], str]


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    detail: str
    hint: str = ""
    fix: Fix | None = None


@dataclass
class DoctorContext:
    workspace: Path
    home: Path
    online: bool = True
    # Replaceable so tests never touch the network or the real uv.
    fetch_latest: Callable[[], str] | None = None
    findings: list[Finding] = field(default_factory=list)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _move_aside(path: Path) -> Path:
    target = path.with_name(f"{path.name}.broken-{_stamp()}")
    path.rename(target)
    return target


def _display(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home().resolve()).as_posix()}"
    except ValueError:
        return str(path)


# --- checks -----------------------------------------------------------------


def check_install(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent import updates

    current = updates.installed_version()
    if current is None:
        try:
            from importlib.metadata import version

            label = f"symphony-code {version(updates.PACKAGE)}"
        except Exception:  # noqa: BLE001
            label = "symphony-code"
        yield Finding("Install", "ok", f"{label} from a source checkout or local path")
        return
    if not ctx.online:
        yield Finding("Install", "ok", f"symphony-code {current} (update check skipped: --offline)")
        return
    try:
        latest = ctx.fetch_latest() if ctx.fetch_latest else _fetch_latest()
    except ssl.SSLError as exc:
        yield Finding(
            "Install", "fail", f"symphony-code {current}; HTTPS certificate check failed: {exc}",
            hint="Set SSL_CERT_FILE to your CA bundle (common behind corporate proxies), then run again.",
        )
        return
    except (OSError, urllib.error.URLError, ValueError) as exc:
        yield Finding("Install", "warn", f"symphony-code {current}; could not reach PyPI ({exc})",
                      hint="Check your network, or run with --offline.")
        return
    if not updates.is_newer(latest, current):
        yield Finding("Install", "ok", f"symphony-code {current} (latest)")
        return
    detail = f"symphony-code {current}; {latest} is available"
    if not updates.pypi_tool_install():
        yield Finding("Install", "warn", detail, hint=f"Upgrade it the way you installed it, e.g. uv tool install symphony-code=={latest}")
        return

    def upgrade() -> str:
        result = updates.apply_update(latest)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "uv tool install failed")
        return f"Updated symphony-code to {latest}"

    yield Finding("Install", "warn", detail, fix=Fix(f"update to {latest} with uv", upgrade))


def _fetch_latest() -> str:
    """Latest PyPI release. Unlike ``updates.latest_version`` it raises, so TLS failures can be named."""
    from coding_agent.tls import https_context
    from coding_agent.updates import PYPI_URL

    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5, context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            raise exc.reason from exc
        raise
    latest = payload.get("info", {}).get("version") if isinstance(payload, dict) else None
    if not isinstance(latest, str) or not latest:
        raise ValueError("PyPI answered without a version")
    return latest


def check_python(ctx: DoctorContext) -> Iterable[Finding]:
    found = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 11):
        yield Finding("Python", "fail", f"{found} at {sys.executable}; Symphony needs 3.11 or newer",
                      hint="Reinstall with a newer Python: uv tool install --python 3.12 symphony-code")
    else:
        yield Finding("Python", "ok", f"{found}")


def check_home(ctx: DoctorContext) -> Iterable[Finding]:
    home = ctx.home
    if not home.exists():
        def create() -> str:
            home.mkdir(parents=True, mode=0o700)
            return f"Created {_display(home)}"

        yield Finding("Home", "warn", f"{_display(home)} does not exist yet", fix=Fix(f"create {_display(home)}", create))
        return
    if not home.is_dir():
        yield Finding("Home", "fail", f"{_display(home)} is not a directory",
                      hint="Move that file away, or point SYMPHONY_HOME at a directory.")
        return
    if not os.access(home, os.W_OK | os.X_OK):
        yield Finding("Home", "fail", f"{_display(home)} is not writable by you",
                      hint=f"Take ownership: sudo chown -R \"$USER\" {home}")
        return
    yield Finding("Home", "ok", _display(home))


def check_config(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent.config import DEFAULT_THEME, CodingAgentConfig, ensure_spawn_settings, load_coding_agent_config, spawn_settings_path

    path = spawn_settings_path(ctx.workspace)
    if not path.exists():
        yield Finding("Config", "ok", f"{_display(path)} not written yet; defaults apply")
        return
    try:
        config = load_coding_agent_config(path=path)
    except Exception as exc:  # noqa: BLE001 - JSON, shape and validation errors alike
        def reset() -> str:
            moved = _move_aside(path)
            ensure_spawn_settings(ctx.workspace, config=CodingAgentConfig())
            return f"Moved the broken file to {moved.name} and wrote defaults"

        yield Finding("Config", "fail", _first_line(exc), fix=Fix(f"move {path.name} aside and write defaults", reset))
        return
    yield Finding("Config", "ok", _display(path))

    if config.theme.casefold() == DEFAULT_THEME:
        return
    from coding_agent.addons.plugins import find_theme
    from coding_agent.commands.themes_cli import available_themes

    try:
        find_theme(available_themes(ctx.workspace, config), config.theme)
    except ValueError:
        def use_default() -> str:
            ensure_spawn_settings(ctx.workspace, overrides={"theme": DEFAULT_THEME})
            return "Switched the theme back to default"

        yield Finding("Theme", "warn", f"config.json picks theme {config.theme!r}, which no enabled plugin provides",
                      fix=Fix("switch back to the default theme", use_default))


def check_user_theme(ctx: DoctorContext) -> Iterable[Finding]:
    path = ctx.home / "theme.toml"
    if not path.is_file():
        return
    try:
        # The theme parser lives in the TUI package; import it only when there is a file to check.
        from coding_agent.tui.theme.load import load_theme

        load_theme(path)
    except Exception as exc:  # noqa: BLE001
        def move() -> str:
            return f"Moved it to {_move_aside(path).name}; the built-in theme applies"

        yield Finding("Theme", "fail", f"{_display(path)} does not load: {_first_line(exc)}",
                      fix=Fix("move theme.toml aside", move))
        return
    yield Finding("Theme", "info", f"{_display(path)} overrides the chosen theme")


def check_providers(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent.config.credentials import load_provider_env
    from core_ai.oauth.store import load_token, oauth_dir
    from core_ai.providers.catalog import configured_provider_ids, get_provider

    load_provider_env(ctx.workspace)
    configured = list(configured_provider_ids())
    for token_file in sorted(oauth_dir().glob("*.json")) if oauth_dir().is_dir() else ():
        provider_id = token_file.stem
        try:
            token = load_token(provider_id)
        except ValueError:
            continue
        if token is None:
            def move(path: Path = token_file) -> str:
                return f"Moved it to {_move_aside(path).name}; sign in again with /login"

            yield Finding("Sign-in", "fail", f"{_display(token_file)} is unreadable",
                          fix=Fix(f"move the broken {provider_id} sign-in aside", move))
            continue
        if token.is_expired() and not token.refresh_token:
            yield Finding("Sign-in", "warn", f"{provider_id} sign-in expired and cannot refresh",
                          hint=f"Open symphony and run /login {provider_id}.")
            continue
        if provider_id not in configured:
            configured.append(provider_id)
    if not configured:
        yield Finding("Providers", "fail", "no model provider is configured",
                      hint="Open symphony and run /login, or put a key such as OPENAI_API_KEY in ~/.symphony/.env.")
        return
    labels = []
    for provider_id in configured:
        try:
            labels.append(get_provider(provider_id).label)
        except Exception:  # noqa: BLE001
            labels.append(provider_id)
    yield Finding("Providers", "ok", ", ".join(labels))


def check_secret_permissions(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent.config.credentials import global_env_path
    from core_ai.oauth.store import oauth_dir

    files = [global_env_path()]
    if oauth_dir().is_dir():
        files += sorted(oauth_dir().glob("*.json"))
    loose = [path for path in files if path.is_file() and stat.S_IMODE(path.stat().st_mode) & 0o077]
    if not loose:
        return

    def tighten() -> str:
        for path in loose:
            path.chmod(0o600)
        return f"Restricted {len(loose)} file(s) to your user (600)"

    names = ", ".join(_display(path) for path in loose)
    yield Finding("Secrets", "warn", f"other users can read {names}", fix=Fix("restrict them to you (chmod 600)", tighten))


def check_active_sessions(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent.addons.persistence.active import list_active
    from coding_agent.resources.usage import process_alive

    directory = ctx.home / "active"
    if not directory.is_dir():
        return
    dead = [record for record in list_active(include_dead=True) if not process_alive(record.pid)]
    old_temps = _old_temps(directory, "*.tmp")
    if dead or old_temps:
        def clean() -> str:
            list_active()  # drops registry files whose process exited
            for path in old_temps:
                path.unlink(missing_ok=True)
            return f"Removed {len(dead) + len(old_temps)} record(s) left by crashed sessions"

        yield Finding("Sessions", "warn", f"{len(dead) + len(old_temps)} record(s) left by sessions that crashed",
                      fix=Fix("remove them", clean))
    # Every session leaves a lock file, even after a clean exit. They are harmless; this only tidies up.
    unused = [path for path in directory.glob("*.lock") if not _lock_held(path)]
    if len(unused) >= UNUSED_LOCKS_WORTH_CLEANING:
        def remove_locks() -> str:
            removed = 0
            for path in unused:
                if not _lock_held(path):
                    path.unlink(missing_ok=True)
                    removed += 1
            return f"Removed {removed} unused session lock file(s)"

        yield Finding("Sessions", "info", f"{len(unused)} unused session lock files",
                      fix=Fix("remove them", remove_locks))


def _lock_held(path: Path) -> bool:
    try:
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
    except OSError:
        return True


def _old_temps(directory: Path, pattern: str) -> list[Path]:
    cutoff = time.time() - STALE_TEMP_SECONDS
    found = []
    for path in directory.glob(pattern):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                found.append(path)
        except OSError:
            continue
    return found


def check_session_store(ctx: DoctorContext) -> Iterable[Finding]:
    legacy = ctx.workspace / ".sessions"
    if legacy.is_dir() and not legacy.is_symlink():
        def migrate() -> str:
            from coding_agent.addons.persistence.jsonl import sessions_dir

            sessions_dir(ctx.workspace)
            return "Moved old sessions into the Symphony home"

        yield Finding("Sessions", "warn", f"{_display(legacy)} holds sessions from an older release",
                      fix=Fix("move them into the Symphony home", migrate))
    temps = []
    for directory in (ctx.home / "sessions", ctx.home / "tui" / "sessions"):
        if directory.is_dir():
            temps += _old_temps(directory, "*.tmp") + _old_temps(directory, "*/*.tmp")
    if temps:
        def clean() -> str:
            for path in temps:
                path.unlink(missing_ok=True)
            return f"Removed {len(temps)} unfinished write(s)"

        yield Finding("Sessions", "warn", f"{len(temps)} unfinished write(s) left by a crash", fix=Fix("remove them", clean))


def check_tools(ctx: DoctorContext) -> Iterable[Finding]:
    if not shutil.which("git"):
        yield Finding("git", "warn", "not on PATH", hint="Install git; the branch, /diff and checkpoints use it.")
    else:
        yield Finding("git", "ok", shutil.which("git") or "")
    if not shutil.which("rg"):
        yield Finding("ripgrep", "info", "not on PATH; search uses the slower built-in walker",
                      hint="Install ripgrep (brew install ripgrep) for fast search.")
    else:
        yield Finding("ripgrep", "ok", shutil.which("rg") or "")


def check_extensions(ctx: DoctorContext) -> Iterable[Finding]:
    from coding_agent.commands.installed import discover, saved_config

    try:
        config = saved_config(ctx.workspace)
    except Exception:  # noqa: BLE001 - check_config already reports a broken config
        return
    skills, plugins = discover(ctx.workspace, config)
    problems = [item for item in (*plugins.diagnostics, *skills.diagnostics) if item.level == "error"]
    count = len(skills.registry.skills)
    enabled = sum(1 for plugin in plugins.plugins if plugin.enabled)
    if not problems:
        yield Finding("Extensions", "ok", f"{_plural(count, 'skill')}, {_plural(enabled, 'plugin')}")
        return
    shown = "; ".join(item.render() for item in problems[:3])
    more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
    yield Finding("Extensions", "warn", f"{len(problems)} problem(s): {shown}{more}",
                  hint="See symphony plugins list and symphony skills list; disable or fix what is listed.")


def check_terminal(ctx: DoctorContext) -> Iterable[Finding]:
    term = os.environ.get("TERM", "")
    if term == "dumb":
        yield Finding("Terminal", "warn", "TERM=dumb; the TUI needs a real terminal", hint="Run symphony in a terminal emulator.")
        return
    color = os.environ.get("COLORTERM", "")
    if color in {"truecolor", "24bit"}:
        yield Finding("Terminal", "ok", f"{term or 'unknown'}, true color")
    else:
        yield Finding("Terminal", "info", f"{term or 'unknown'} without true color; theme colors are approximated")


CHECKS: tuple[Callable[[DoctorContext], Iterable[Finding]], ...] = (
    check_install,
    check_python,
    check_home,
    check_config,
    check_user_theme,
    check_providers,
    check_secret_permissions,
    check_active_sessions,
    check_session_store,
    check_extensions,
    check_tools,
    check_terminal,
)


def run_checks(ctx: DoctorContext, checks: Sequence[Callable[[DoctorContext], Iterable[Finding]]] = CHECKS) -> list[Finding]:
    """Run every check. A check that crashes is itself a finding, so one bug cannot hide the rest."""
    findings: list[Finding] = []
    for check in checks:
        try:
            findings.extend(check(ctx))
        except Exception as exc:  # noqa: BLE001
            name = check.__name__.removeprefix("check_").replace("_", " ").capitalize()
            findings.append(Finding(name, "fail", f"check crashed: {_first_line(exc)}"))
    return findings


def apply_fixes(findings: Sequence[Finding]) -> list[tuple[Finding, bool, str]]:
    results = []
    for finding in findings:
        if finding.fix is None:
            continue
        try:
            results.append((finding, True, finding.fix.apply()))
        except Exception as exc:  # noqa: BLE001
            results.append((finding, False, _first_line(exc)))
    return results


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text.splitlines()[0]


# --- command line -------------------------------------------------------------

_MARKS = {"ok": ("✓", "green"), "info": ("·", "dim"), "warn": ("!", "yellow"), "fail": ("✗", "red")}


def render(findings: Sequence[Finding], console) -> None:
    from rich.table import Table
    from rich.text import Text

    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True, style="bold")
    grid.add_column()
    for finding in findings:
        mark, color = _MARKS[finding.status]
        detail = Text(finding.detail, style="dim" if finding.status in {"ok", "info"} else "")
        if finding.fix is not None:
            detail.append(f"\nfix: {finding.fix.summary}", style="cyan")
        elif finding.hint:
            detail.append(f"\n{finding.hint}", style="dim")
        grid.add_row(Text(mark, style=color), finding.check, detail)
    console.print(grid)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="symphony doctor",
        description="Check the Symphony install, configuration and sign-ins, and repair what can be repaired.",
    )
    parser.add_argument("--fix", action="store_true", help="apply every available fix without asking")
    parser.add_argument("--check", action="store_true", help="only report; never change anything")
    parser.add_argument("--offline", action="store_true", help="skip the PyPI update check")
    parser.add_argument("--workspace", default=None, help="project directory to check (default: .)")
    return parser


def main(argv: Sequence[str] | None = None, *, stdin=None, console=None) -> int:
    from rich.console import Console

    arguments = build_parser().parse_args(argv)
    if arguments.fix and arguments.check:
        build_parser().error("--fix and --check cannot be combined")
    from coding_agent.config import symphony_dir

    console = console or Console(highlight=False)
    stdin = stdin or sys.stdin
    ctx = DoctorContext(
        workspace=Path(arguments.workspace or ".").expanduser().resolve(),
        home=symphony_dir(),
        online=not arguments.offline,
    )
    console.print("[bold]Symphony doctor[/]\n")
    findings = run_checks(ctx)
    render(findings, console)

    fixable = [finding for finding in findings if finding.fix is not None]
    if fixable and not arguments.check:
        noun = "problem" if len(fixable) == 1 else "problems"
        console.print()
        if not arguments.fix:
            if not stdin.isatty():
                console.print(f"{len(fixable)} {noun} can be fixed. Run [bold]symphony doctor --fix[/] to repair them.")
                return _exit_code(findings)
            console.print(f"{len(fixable)} {noun} can be fixed. Fix now? [Y/n] ", end="")
            answer = stdin.readline().strip().casefold()
            if answer not in {"", "y", "yes"}:
                return _exit_code(findings)
        for finding, ok, message in apply_fixes(fixable):
            mark, color = ("✓", "green") if ok else ("✗", "red")
            console.print(f"[{color}]{mark}[/] [bold]{finding.check}[/] {message}")
        findings = run_checks(ctx)
        left = [finding for finding in findings if finding.status in {"warn", "fail"}]
        console.print()
        if left:
            console.print(f"{len(left)} issue(s) still need you:")
            render(left, console)
        else:
            console.print("[green]Everything checks out.[/]")
        return _exit_code(findings)

    problems = [finding for finding in findings if finding.status in {"warn", "fail"}]
    if not problems:
        console.print("\n[green]Everything checks out.[/]")
    return _exit_code(findings)


def _exit_code(findings: Sequence[Finding]) -> int:
    return 1 if any(finding.status == "fail" for finding in findings) else 0


__all__ = ["CHECKS", "DoctorContext", "Finding", "Fix", "apply_fixes", "main", "run_checks"]
