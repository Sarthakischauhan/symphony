"""Session artifacts: the capture filter, each kind, versioning, the add-on and stdio."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_harness import EventSink
from core_harness.models import ToolCall, ToolResult

from coding_agent.addons.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactsAddon,
    ArtifactStore,
    snapshot_path,
)
from coding_agent.addons.artifacts.addon import site_of
from coding_agent.addons.artifacts.noise import git_tracked, is_noise
from coding_agent.addons.artifacts.capture import snapshot_image_part
from coding_agent.addons.artifacts.kinds import kind_of
from coding_agent.addons.artifacts.store import content_digest
from coding_agent.agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig
from coding_agent.protocols.stdio.requests import artifact_get, artifact_list
from coding_agent.tools.save_artifact import SaveArtifactArgs, SaveArtifactTool
from coding_agent.tui.chrome import SessionChrome
from coding_agent.tui.screens.history import load_session_history
from coding_agent.tui.transcript import artifact as artifact_row

from scripted_registry import ScriptedRegistry

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'


def png(width: int = 2, height: int = 2) -> bytes:
    """A valid RGB png, built at test time so no binary is committed."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


# Capture filter


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("page.html", ArtifactKind.HTML), ("data.CSV", ArtifactKind.CSV), ("x.json", ArtifactKind.JSON),
        ("a.png", ArtifactKind.IMAGE), ("a.jpg", ArtifactKind.IMAGE), ("a.jpeg", ArtifactKind.IMAGE),
        ("a.webp", ArtifactKind.IMAGE), ("a.gif", ArtifactKind.IMAGE), ("a.svg", ArtifactKind.IMAGE),
        ("notes.txt", None), ("style.css", None), ("app.py", None), ("page.htm", None),
        ("a.bmp", None), ("Makefile", None), ("doc.pdf", None),
    ],
)
def test_capture_filter_keeps_only_the_four_kinds(name: str, kind: ArtifactKind | None) -> None:
    assert kind_of(Path(name)) is kind


def test_kinds_are_exactly_html_csv_json_image() -> None:
    assert [kind.value for kind in ArtifactKind] == ["html", "csv", "json", "image"]


# Each kind


def test_single_html_file(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<h1>hi</h1>")
    captured = snapshot_path(tmp_path / "page.html", tmp_path)
    assert (captured.kind, captured.entry, captured.mime, captured.source) == (
        ArtifactKind.HTML, "page.html", "text/html", "page.html")


def test_html_site_folder_keeps_its_assets(tmp_path: Path) -> None:
    site = tmp_path / "site"
    (site / "css").mkdir(parents=True)
    (site / "node_modules").mkdir()
    (site / ".cache").mkdir()
    (site / "index.html").write_text('<link rel="stylesheet" href="css/app.css"><h1>site</h1>')
    (site / "css" / "app.css").write_text("h1{color:red}")
    (site / "node_modules" / "dep.js").write_text("x")
    (site / ".cache" / "c").write_text("x")
    for captured in (snapshot_path(site / "index.html", tmp_path), snapshot_path(site, tmp_path, ArtifactKind.HTML)):
        assert captured.kind is ArtifactKind.HTML and captured.entry == "index.html"
        assert captured.source == "site" and captured.title == "site"
        assert [name for name, _ in captured.files] == ["css/app.css", "index.html"]
    with pytest.raises(ArtifactError, match="only an html"):
        snapshot_path(site, tmp_path, ArtifactKind.CSV)
    (site / "index.html").unlink()
    with pytest.raises(ArtifactError, match="index.html"):
        snapshot_path(site, tmp_path)


def test_index_html_at_the_workspace_root_is_a_single_file(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>root</p>")
    (tmp_path / "other.txt").write_text("not part of it")
    assert [name for name, _ in snapshot_path(tmp_path / "index.html", tmp_path).files] == ["index.html"]


def test_csv_must_be_utf8(tmp_path: Path) -> None:
    (tmp_path / "ok.csv").write_text("a,b\n1,2\n")
    assert snapshot_path(tmp_path / "ok.csv", tmp_path).mime == "text/csv"
    (tmp_path / "bad.csv").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ArtifactError, match="not valid csv"):
        snapshot_path(tmp_path / "bad.csv", tmp_path)


def test_json_must_parse(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text('{"a": [1, 2]}')
    assert snapshot_path(tmp_path / "ok.json", tmp_path).mime == "application/json"
    (tmp_path / "bad.json").write_text("{nope")
    with pytest.raises(ArtifactError, match="not valid json"):
        snapshot_path(tmp_path / "bad.json", tmp_path)


def test_images_by_suffix_and_by_content(tmp_path: Path) -> None:
    (tmp_path / "chart.png").write_bytes(png())
    (tmp_path / "logo.svg").write_bytes(SVG)
    (tmp_path / "plot.bin").write_bytes(png())
    (tmp_path / "fake.txt").write_text("hello")
    assert snapshot_path(tmp_path / "chart.png", tmp_path).mime == "image/png"
    assert snapshot_path(tmp_path / "logo.svg", tmp_path).mime == "image/svg+xml"
    assert snapshot_path(tmp_path / "plot.bin", tmp_path, ArtifactKind.IMAGE).mime == "image/png"
    with pytest.raises(ArtifactError, match="not a png"):
        snapshot_path(tmp_path / "fake.txt", tmp_path, ArtifactKind.IMAGE)
    with pytest.raises(ArtifactError, match="not an html"):
        snapshot_path(tmp_path / "fake.txt", tmp_path)


def test_inline_image_part(tmp_path: Path) -> None:
    del tmp_path
    part = {"type": "image", "data": base64.b64encode(png()).decode(), "filename": "../../evil"}
    captured = snapshot_image_part(part, "call-1", 0)
    assert captured is not None
    assert (captured.source, captured.entry, captured.mime) == ("call-1#image-1", "evil.png", "image/png")
    assert snapshot_image_part({"type": "image", "data": base64.b64encode(b"text").decode()}, "c", 0) is None
    assert snapshot_image_part({"type": "text", "text": "x"}, "c", 0) is None


def test_symlinks_are_not_captured(tmp_path: Path) -> None:
    (tmp_path / "real.csv").write_text("a\n")
    (tmp_path / "link.csv").symlink_to(tmp_path / "real.csv")
    with pytest.raises(ArtifactError, match="regular file"):
        snapshot_path(tmp_path / "link.csv", tmp_path)


# Store


def test_store_versions_by_sha256(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "sessions")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    data = workspace / "data.csv"
    data.write_text("a\n1\n")
    first = store.save("s1", snapshot_path(data, workspace), "c1")
    assert first is not None and first.created
    assert store.save("s1", snapshot_path(data, workspace), "c2") is None
    data.write_text("a\n2\n")
    second = store.save("s1", snapshot_path(data, workspace), "c3")
    assert second is not None and not second.created
    manifest = second.manifest
    assert (manifest.id, manifest.version, manifest.entry, manifest.tool_call_id) == (
        first.manifest.id, 2, "v2/data.csv", "c3")
    assert manifest.created_at == first.manifest.created_at
    assert manifest.sha256 == content_digest((("data.csv", b"a\n2\n"),)) and manifest.size == 4

    folder = tmp_path / "sessions" / "s1" / "artifacts" / manifest.id
    assert sorted(path.name for path in folder.iterdir()) == ["manifest.json", "v1", "v2"]
    assert (folder / "v1" / "data.csv").read_text() == "a\n1\n"
    assert json.loads((folder / "manifest.json").read_text())["version"] == 2
    index = json.loads((tmp_path / "sessions" / "s1" / "artifacts" / "index.json").read_text())
    assert [row["version"] for row in index["artifacts"]] == [2]
    assert [row.id for row in store.manifests("s1")] == [manifest.id]
    assert store.get("s1", manifest.id) == manifest
    assert store.files("s1", manifest) == ["data.csv"]


def test_store_rejects_traversal_and_unknown_ids(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "sessions")
    (tmp_path / "x.json").write_text("{}")
    saved = store.save("s1", snapshot_path(tmp_path / "x.json", tmp_path), "c1")
    assert saved is not None
    aid = saved.manifest.id
    assert store.file("s1", aid, "v1/x.json").read_text() == "{}"
    for relative in ("../../../secret", "v1/../../x"):
        with pytest.raises(ValueError):
            store.file("s1", aid, relative)
    # A leading slash stays inside the artifact folder.
    with pytest.raises(KeyError):
        store.file("s1", aid, "/etc/passwd")
    with pytest.raises(KeyError):
        store.file("s1", aid, "v1")
    with pytest.raises(ValueError):
        store.folder("s1", "../s2")
    with pytest.raises(ValueError):
        store.directory("..")
    with pytest.raises(KeyError):
        store.get("s1", "0" * 16)
    assert store.manifests("empty") == []


# save_artifact


def test_save_artifact_rejects_other_kinds(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SaveArtifactArgs.model_validate({"path": "a.txt", "kind": "file"})
    (tmp_path / "out.txt").write_text("a,b\n")
    (tmp_path / "bad.json").write_text("{")
    tool = SaveArtifactTool(tmp_path)
    assert tool.run("out.txt", ArtifactKind.CSV, "Report") == "saved out.txt as csv artifact 'Report'"
    assert tool.run("bad.json", ArtifactKind.JSON).startswith("error: cannot save bad.json")
    assert tool.run("out.txt", ArtifactKind.IMAGE).startswith("error:")


# Add-on


def test_addon_skips_failed_calls_reads_and_other_files(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "sessions")
    addon = ArtifactsAddon(store, tmp_path)
    (tmp_path / "a.png").write_bytes(png())
    (tmp_path / "notes.txt").write_text("x")
    image = [{"type": "image", "data": base64.b64encode(png()).decode()}]
    calls = [
        (ToolCall(id="1", name="write_file", arguments={"path": "notes.txt"}), ToolResult(status="success", content="ok")),
        (ToolCall(id="2", name="read_file", arguments={"path": "a.png"}), ToolResult(status="success", content=image)),
        (ToolCall(id="3", name="write_file", arguments={"path": "a.png"}), ToolResult(status="success", content="ok")),
        (ToolCall(id="4", name="browser", arguments={}), ToolResult(status="success", content=image)),
    ]
    sources = [captured.source for call, result in calls for captured in addon.snapshots(call, result)]
    assert sources == ["a.png", "4#image-1"]


def test_agent_run_emits_created_then_updated_and_serves_stdio(tmp_path: Path) -> None:
    script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>v1</h1>"}),
         ("write_file", {"path": "site/app.css", "content": "h1{}"}),
         ("write_file", {"path": "data.csv", "content": "a\n1\n"})],
        [("write_file", {"path": "data.csv", "content": "a\n1\n"})],
        [("write_file", {"path": "data.csv", "content": "a\n2\n"}),
         ("bash", {"command": "printf '{\"ok\": true}' > out.txt"})],
        [("save_artifact", {"path": "out.txt", "kind": "json", "title": "Result"}),
         ("save_artifact", {"path": "out.txt", "kind": "file"})],
    ]
    sink = EventSink()
    agent = CodingAgent(
        registry=ScriptedRegistry({"build": script}),
        model_id="fake:test-model",
        workspace=tmp_path,
        sink=sink,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False), langfuse=LangfuseConfig(enabled=False), unattended=True
        ),
    )
    asyncio.run(agent.run("build"))

    events = [(event.event_type, dict(event.payload)) for event in sink.events
              if event.event_type.startswith("artifact_")]
    assert [(name, body["title"], body["version"]) for name, body in events] == [
        ("artifact_created", "site", 1),
        # Its stylesheet versions the whole site.
        ("artifact_updated", "site", 2),
        ("artifact_created", "data.csv", 1),
        ("artifact_updated", "data.csv", 2),
        ("artifact_created", "Result", 1),
    ]
    site = events[0][1]
    assert Path(site["path"]).read_text() == "<h1>v1</h1>" and site["entry"] == "v1/index.html"
    assert events[1][1]["entry"] == "v2/index.html"
    assert Path(site["path"]).is_relative_to(agent.persistence.root)

    listed = artifact_list(agent, "r1", agent.session_id)
    assert listed["type"] == "artifacts" and listed["request_id"] == "r1"
    assert [row["kind"] for row in listed["artifacts"]] == ["html", "csv", "json"]
    got = artifact_get(agent, "r2", agent.session_id, site["id"])
    assert got["artifact"]["id"] == site["id"] and got["files"] == ["app.css", "index.html"]
    assert got["path"] == events[1][1]["path"]


def test_child_addon_stores_into_the_parent_session(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "sessions")
    parent = ArtifactsAddon(store, tmp_path)
    child = parent.fork_for_child(None)
    assert isinstance(child, ArtifactsAddon)
    assert child.store is store and child.owner is parent.owner


def test_site_of_finds_the_website_folder_below_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("root")
    (tmp_path / "web" / "img").mkdir(parents=True)
    (tmp_path / "web" / "index.html").write_text("site")
    assert site_of(tmp_path / "web" / "img" / "logo.png", tmp_path) == tmp_path / "web"
    assert site_of(tmp_path / "web" / "app.css", tmp_path) == tmp_path / "web"
    # The workspace itself is never a site; nor is anything outside it.
    assert site_of(tmp_path / "notes.css", tmp_path) is None
    assert site_of(tmp_path.parent / "x.css", tmp_path) is None


def test_tui_artifact_row_opens_the_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(artifact_row.webbrowser, "open", opened.append)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    entry = tmp_path / "s" / "artifacts" / "a" / "v1" / "index.html"
    row = artifact_row.ArtifactRow("site", "html · v1", entry)
    assert row.archive_text() == f"Artifact: site ({entry})"
    assert artifact_row.display_path(entry) == "~/s/artifacts/a/v1/index.html"

    class Click:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    click = Click()
    row.on_click(click)
    assert opened == [entry.as_uri()] and click.stopped


# Noise


@pytest.mark.parametrize(
    "relative",
    [
        "package.json", "web/package-lock.json", "npm-shrinkwrap.json", "tsconfig.json", "tsconfig.node.json",
        "app/tsconfig.build.json", "eslint.config.json", "renovate.config.json", "deno.lock.json",
        "x/composer-lock.json", "node_modules/pkg/data.json", "a/node_modules/b/index.html",
        ".git/info/x.json", "dist/index.html", "web/dist/report.csv", "build/chart.png", "pkg/build/out.json",
    ],
)
def test_noise_files_are_not_auto_captured(tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}" if path.suffix == ".json" else "a\n")
    assert is_noise(path, tmp_path)
    addon = ArtifactsAddon(ArtifactStore(tmp_path / "sessions"), tmp_path)
    call = ToolCall(id="w", name="write_file", arguments={"path": relative})
    assert list(addon.snapshots(call, ToolResult(status="success", content="ok"))) == []


@pytest.mark.parametrize(
    "name",
    ["yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "composer.lock", "Cargo.lock", "poetry.lock",
     "uv.lock", "Gemfile.lock", "Pipfile.lock", "flake.lock"],
)
def test_lockfiles_are_noise(tmp_path: Path, name: str) -> None:
    assert is_noise(tmp_path / name, tmp_path)


@pytest.mark.parametrize(
    "relative", ["report.json", "data/rows.csv", "site/index.html", "builder/chart.png", "distance.json", "config.json"],
)
def test_outputs_are_not_noise(tmp_path: Path, relative: str) -> None:
    assert not is_noise(tmp_path / relative, tmp_path)


def test_vite_project_index_is_not_captured_as_a_site(tmp_path: Path) -> None:
    app = tmp_path / "web"
    app.mkdir()
    (app / "package.json").write_text('{"name": "web"}')
    (app / "vite.config.ts").write_text("export default {}\n")
    (app / "index.html").write_text('<script type="module" src="/src/main.ts"></script>\n')
    (app / "src").mkdir()
    (app / "src" / "main.ts").write_text("console.log(1)\n")
    addon = ArtifactsAddon(ArtifactStore(tmp_path / "sessions"), tmp_path)
    call = ToolCall(id="w", name="write_file", arguments={"path": "web/index.html"})
    assert list(addon.snapshots(call, ToolResult(status="success", content="ok"))) == []
    assert site_of(app / "src" / "main.ts", tmp_path) is None


def test_generated_site_is_still_captured_beside_an_app(tmp_path: Path) -> None:
    app = tmp_path / "web"
    app.mkdir()
    (app / "package.json").write_text("{}")
    page = tmp_path / "preview"
    page.mkdir()
    (page / "index.html").write_text("<h1>preview</h1>")
    addon = ArtifactsAddon(ArtifactStore(tmp_path / "sessions"), tmp_path)
    call = ToolCall(id="w", name="write_file", arguments={"path": "preview/index.html"})
    captured = list(addon.snapshots(call, ToolResult(status="success", content="ok")))
    assert [item.source for item in captured] == ["preview"]


def test_noise_can_still_be_saved_explicitly(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x"}')
    addon = ArtifactsAddon(ArtifactStore(tmp_path / "sessions"), tmp_path)
    call = ToolCall(id="s", name="save_artifact", arguments={"path": "package.json", "kind": "json"})
    assert [c.source for c in addon.snapshots(call, ToolResult(status="success", content="ok"))] == ["package.json"]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_patched_tracked_html_and_json_are_source_edits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "site").mkdir(parents=True)
    git(repo, "init", "-q")
    for name, body in {"page.html": "<p>x</p>", "data.json": "{}", "rows.csv": "a\n",
                       "site/index.html": "<p>s</p>", "fresh.json": "{}"}.items():
        (repo / name).write_text(body)
    git(repo, "add", "page.html", "data.json", "rows.csv", "site/index.html")
    assert git_tracked(repo / "page.html") and not git_tracked(repo / "fresh.json")
    assert not git_tracked(tmp_path / "outside.json")
    addon = ArtifactsAddon(ArtifactStore(tmp_path / "sessions"), repo)

    def captured(tool: str, path: str) -> list[str]:
        call = ToolCall(id="p", name=tool, arguments={"path": path})
        return [c.source for c in addon.snapshots(call, ToolResult(status="success", content="ok"))]

    # Patching tracked html or json edits source; csv, untracked files, sites and writes still count.
    assert captured("patch", "page.html") == []
    assert captured("patch", "data.json") == []
    assert captured("patch", "rows.csv") == ["rows.csv"]
    assert captured("patch", "fresh.json") == ["fresh.json"]
    assert captured("patch", "site/index.html") == ["site"]
    assert captured("write_file", "page.html") == ["page.html"]
    save = ToolCall(id="s", name="save_artifact", arguments={"path": "page.html", "kind": "html"})
    assert [c.source for c in addon.snapshots(save, ToolResult(status="success", content="ok"))] == ["page.html"]


def test_resumed_tui_session_shows_its_artifact_rows(tmp_path: Path) -> None:
    script = [[("write_file", {"path": "data.csv", "content": "a\n1\n"})],
              [("write_file", {"path": "data.csv", "content": "a\n2\n"}),
               ("write_file", {"path": "notes.json", "content": "{}"})]]
    config = CodingAgentConfig(
        learning=LearningConfig(enabled=False), langfuse=LangfuseConfig(enabled=False), unattended=True
    )
    first = CodingAgent(registry=ScriptedRegistry({"go": script}), model_id="fake:test-model",
                        workspace=tmp_path, config=config)
    asyncio.run(first.run("go"))
    resumed = CodingAgent(registry=ScriptedRegistry({}), model_id="fake:test-model", workspace=tmp_path,
                          config=config, session_id=first.session_id)

    class View:
        def __init__(self) -> None:
            self.rows: list[tuple[str, str, Path]] = []

        def add_notice(self, text: str, tone: str = "info") -> None:
            del text, tone

        _tools: dict[str, object] = {}

        def mount_transcript_batch(self, widgets: list[object]) -> None:
            del widgets

        def reset_session_chrome(self, session: SessionChrome) -> None:
            self.rows = list(session.artifacts.values())

        def finalize_transcript_history(self) -> None:
            pass

    view = View()
    asyncio.run(load_session_history(resumed, view))
    assert [(title, detail) for title, detail, _ in view.rows] == [("data.csv", "csv · v2"), ("notes.json", "json · v1")]
    assert view.rows[0][2].read_text() == "a\n2\n"
