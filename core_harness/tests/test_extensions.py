"""User-addon loader: manifests, confinement, failure isolation, purity."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core_harness.extensions import dispatch_event, dispose_addons, load_addons

GOOD = """
from core_harness import Tool
from core_harness.extensions import CommandSpec

disposed = []

def setup(api):
    api.register_tool(Tool(lambda: "ok", name="{name}_tool"))
    api.register_command(CommandSpec("{name}", "demo", lambda argument: "hi"))
    api.on("turn_completed", lambda event, payload: None)

def dispose():
    disposed.append(True)
"""


def _addon(root: Path, name: str, source: str, manifest: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "addon.py").write_text(source.replace("{name}", name), encoding="utf-8")
    if manifest is not None:
        (folder / "addon.toml").write_text(manifest, encoding="utf-8")
    return folder


def test_bare_addon_py_and_manifest_both_load(tmp_path: Path) -> None:
    _addon(tmp_path, "bare", GOOD)
    _addon(tmp_path, "toml", GOOD.replace("def setup", "def make"),
           'name = "toml"\nversion = "1.2.3"\nentry = "addon.py"\nfactory = "make"\n')
    snapshot = load_addons([tmp_path])
    assert [(a.name, a.version) for a in snapshot.loaded] == [("bare", "0.0.0"), ("toml", "1.2.3")]
    assert snapshot.tool_names == {"bare_tool", "toml_tool"}
    assert [c.name for c in snapshot.commands] == ["bare", "toml"]
    assert snapshot.failed == ()


def test_bad_addons_are_skipped_with_a_diagnostic(tmp_path: Path) -> None:
    _addon(tmp_path, "a_import", "import does_not_exist_anywhere\n")
    _addon(tmp_path, "b_setup", "def setup(api):\n    raise RuntimeError('boom')\n")
    _addon(tmp_path, "c_nofactory", "setup = 3\n")
    _addon(tmp_path, "d_exit", "raise SystemExit(2)\n")
    _addon(tmp_path, "good", GOOD)
    snapshot = load_addons([tmp_path])
    assert [a.name for a in snapshot.loaded] == ["good"]
    phases = {f.name: (f.phase, f.error) for f in snapshot.failed}
    assert phases["a_import"][0] == "import" and "ModuleNotFoundError" in phases["a_import"][1]
    assert phases["b_setup"] == ("setup", "RuntimeError: boom")
    assert phases["c_nofactory"][0] == "import"
    assert phases["d_exit"][0] == "import"


def test_failing_hook_is_isolated_per_call(tmp_path: Path) -> None:
    _addon(tmp_path, "hooky", """
calls = []
def setup(api):
    api.on("turn_completed", lambda event, payload: (_ for _ in ()).throw(ValueError("hook")))
    api.on("turn_completed", lambda event, payload: calls.append(event))
""")
    snapshot = load_addons([tmp_path])
    first = dispatch_event(snapshot, "turn_completed", {})
    second = dispatch_event(snapshot, "turn_completed", {})
    assert [(f.name, f.phase) for f in first + second] == [("hooky", "hook")] * 2
    assert dispatch_event(snapshot, "run_started", {}) == ()


def test_unsubscribe_and_dispose_failures(tmp_path: Path) -> None:
    _addon(tmp_path, "bad_dispose", """
seen = []
def setup(api):
    off = api.on("turn_completed", lambda event, payload: seen.append(event))
    off()
def dispose():
    raise OSError("dispose")
""")
    snapshot = load_addons([tmp_path])
    assert dispatch_event(snapshot, "turn_completed", {}) == ()
    failures = dispose_addons(snapshot.loaded)
    assert [(f.name, f.phase, f.error) for f in failures] == [("bad_dispose", "dispose", "OSError: dispose")]


def test_unknown_event_fails_setup(tmp_path: Path) -> None:
    _addon(tmp_path, "typo", "def setup(api):\n    api.on('turn_finished', print)\n")
    assert load_addons([tmp_path]).failed[0].phase == "setup"


def test_reserved_names_are_rejected(tmp_path: Path) -> None:
    _addon(tmp_path, "persistence", GOOD)
    snapshot = load_addons([tmp_path], reserved_names={"persistence"})
    assert snapshot.loaded == ()
    assert snapshot.failed[0].name == "persistence"
    assert "built-in" in snapshot.notices[0]


def test_entry_must_stay_inside_the_addon(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("def setup(api):\n    pass\n", encoding="utf-8")
    root = tmp_path / "addons"
    _addon(root, "dotdot", "", 'entry = "../../outside.py"\n')
    _addon(root, "absolute", "", f'entry = "{outside.as_posix()}"\n')
    link = _addon(root, "link", "", 'entry = "escape.py"\n')
    (link / "escape.py").symlink_to(outside)
    snapshot = load_addons([root])
    assert snapshot.loaded == ()
    assert {f.name: f.phase for f in snapshot.failed} == {
        "dotdot": "manifest", "absolute": "manifest", "link": "manifest",
    }
    assert all("escapes" in f.error or "relative" in f.error for f in snapshot.failed)


def test_unique_module_names(tmp_path: Path) -> None:
    _addon(tmp_path, "same", GOOD)
    first = load_addons([tmp_path]).loaded[0]
    second = load_addons([tmp_path]).loaded[0]
    assert first.dispose is not second.dispose
    names = [name for name in sys.modules if name.startswith("symphony_addon_same_")]
    assert len(names) >= 2


def test_missing_root_is_empty(tmp_path: Path) -> None:
    assert load_addons([tmp_path / "nope"]).loaded == ()


def test_extensions_package_has_no_product_imports() -> None:
    script = (
        "import sys, core_harness.extensions, core_harness.extensions.loader\n"
        "print(','.join(n for n in sys.modules if n.split('.')[0] in {'coding_agent', 'core_server', 'textual'}))\n"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=dict(os.environ), check=True, timeout=60)
    assert done.stdout.strip() == ""
