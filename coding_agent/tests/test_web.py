"""Exercise HTTP policy, historical storage, and the real agent worker transport."""

import asyncio
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from coding_agent.addons.artifacts import ArtifactStore, snapshot_path
from coding_agent.addons.persistence import register_active, release_active, sessions_dir
from coding_agent.web.bundle import resolve_static
from coding_agent.web.server import Server, stage_attachments
from coding_agent.web.sessions import Sessions, registry


@pytest.fixture
def model(monkeypatch):
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({"data": [{"id": "web-test"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            messages = data["messages"]
            prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            if "slow" in str(prompt):
                time.sleep(1)
            if "write" in str(prompt).lower() and messages[-1]["role"] != "tool":
                delta = {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "write-1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "table.csv", "content": "a,b\n1,2\n"} if "csv" in str(prompt)
                                    else {"path": "web-result.txt", "content": "Web works\n"}
                                ),
                            },
                        }
                    ]
                }
                reason = "tool_calls"
            else:
                delta, reason = {"content": "Web task completed"}, "stop"
            chunks = [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
            ]
            body = ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LOCAL_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LOCAL_MODEL", "web-test")
    yield
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def static(tmp_path_factory):
    # No installed bundle: the source checkout's web-ui is built (or reused).
    return resolve_static(tmp_path_factory.mktemp("web"))


@pytest.fixture
def web(tmp_path, model, static):
    sessions = Sessions(tmp_path, "local:web-test")
    server = Server(("127.0.0.1", 0), sessions, static)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def request(web, path="/api/sessions", data=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", web.server_port, timeout=10)
    fields = {"X-Symphony-Token": web.token, "Content-Type": "application/json", **(headers or {})}
    conn.request("POST" if data is not None else "GET", path, json.dumps(data) if data is not None else None, fields)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, json.loads(body) if response.headers.get("Content-Type") == "application/json" else body


def wait(worker, predicate):
    with worker.condition:
        assert worker.condition.wait_for(lambda: predicate(worker), timeout=15), worker.events


@pytest.mark.slow
def test_client_disconnects_are_not_logged(web, capsys):
    import socket
    import struct

    conn = socket.create_connection(("127.0.0.1", web.server_port))
    conn.sendall(b"GET /api/sessions HTTP/1.1\r\n")
    # SO_LINGER 0 makes close() send RST, like a browser dropping a socket.
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    conn.close()
    time.sleep(0.3)
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.slow
def test_security_policy(web):
    assert request(web)[0] == 200
    for headers in [
        {"Origin": "https://evil.example"},
        {"Host": "evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Symphony-Token": "bad"},
    ]:
        assert request(web, headers=headers)[0] == 403
        assert request(web, data={}, headers=headers)[0] == 403
    assert request(web, data={}, headers={"Content-Type": "text/plain"})[0] == 403
    assert request(web, "/../server.py")[0] == 404
    assert request(web, "/")[0] == 200


@pytest.mark.slow
def test_real_worker_stream_history_refresh_and_recovery(web):
    status, data = request(web, data={})
    assert status == 200, data
    sid = data["session_id"]
    worker = web.sessions.workers[sid]
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "Say hello"})[0] == 200
    wait(worker, lambda w: any(e["data"].get("type") == "done" for e in w.events))
    assert any(e["data"].get("event") == "text_delta" for e in worker.events)
    # Browser refresh receives the same baseline and a replay from sequence 1.
    assert request(web, f"/api/sessions/{sid}")[1]["owned"]
    conn = http.client.HTTPConnection("127.0.0.1", web.server_port, timeout=10)
    conn.request("GET", f"/api/sessions/{sid}/events", headers={"X-Symphony-Token": web.token, "Last-Event-ID": "1"})
    response = conn.getresponse()
    assert response.status == 200
    assert response.readline() == b"id: 2\n"
    response.close()
    conn.close()
    history = web.sessions.history(sid)
    assert any("Web task completed" in str(m["content"]) for m in history["messages"])
    # The prompt arrives as the protocol's run_started event, not a host frame.
    assert any(e["data"].get("event") == "run_started" for e in worker.events)
    assert not any(e["data"].get("type") == "user" for e in worker.events)
    worker.close()
    assert request(web, f"/api/sessions/{sid}/resume", {})[0] == 200
    assert web.sessions.workers[sid] is not worker
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "Continue"})[0] == 200
    wait(web.sessions.workers[sid], lambda w: any(e["data"].get("type") == "done" for e in w.events))


@pytest.mark.slow
def test_warm_starts_the_control_worker_before_any_request(web):
    assert web.sessions._control is None
    web.sessions.warm()
    deadline = time.monotonic() + 15
    while web.sessions._control is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert web.sessions._control is not None and web.sessions._control.alive
    status, info = request(web, "/api/info")
    assert status == 200 and info["path"] == str(web.sessions.workspace)


@pytest.mark.slow
def test_workspace_info_models_and_commands_come_from_the_worker(web):
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "web-branch", str(web.sessions.workspace)], check=True)
    web.sessions.close()
    web.sessions = Sessions(web.sessions.workspace, "local:web-test")
    status, info = request(web, "/api/info")
    assert status == 200, info
    # Workspace and branch arrive in the worker's ready frame.
    assert info["path"] == str(web.sessions.workspace) and info["name"] == web.sessions.workspace.name
    assert info["branch"] == "web-branch"
    status, catalog = request(web, "/api/models")
    assert status == 200, catalog
    # The chat SDK registry shape, built from the worker's model/list reply.
    # Unqualified LOCAL_MODEL resolves to the first configured provider, so the
    # catalog default follows the developer shell. The worker's own model does not.
    assert isinstance(catalog["defaultProviderId"], str) and catalog["defaultProviderId"]
    assert catalog["default"]
    local = next(p for p in catalog["providers"] if p["id"] == "local")
    assert any(m["id"] == "local:web-test" for m in local["models"])
    # contextWindow is the frame's context_limit, only when it is a positive int.
    assert all(isinstance(m.get("contextWindow", 1), int) for p in catalog["providers"] for m in p["models"])
    status, commands = request(web, "/api/commands")
    assert status == 200 and any(item["name"] == "help" for item in commands)


@pytest.mark.slow
def test_model_switch_uses_the_protocol_on_the_live_worker(web):
    status, data = request(web, data={"model": "local:web-test"})
    assert status == 200, data
    sid = data["session_id"]
    worker = web.sessions.workers[sid]
    assert request(web, f"/api/sessions/{sid}")[1]["model"] == "local:web-test"
    assert request(web, f"/api/sessions/{sid}/resume", {"model": 7})[0] == 400
    # An unknown model is rejected by the worker; the process keeps running.
    assert request(web, f"/api/sessions/{sid}/resume", {"model": "local:missing"})[0] == 409
    assert web.sessions.workers[sid] is worker and worker.alive
    # The worker validates effort and rejects overlapping runs itself.
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "hi", "reasoning_effort": "huge"})[0] == 200
    wait(worker, lambda w: any("Unsupported reasoning effort" in str(e["data"].get("message")) for e in w.events))
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "slow hi"})[0] == 200
    wait(worker, lambda w: any(e["data"].get("event") == "run_started" for e in w.events))
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "overlap"})[0] == 200
    wait(worker, lambda w: any("run rejected" in str(e["data"].get("message")) for e in w.events))
    assert request(web, f"/api/sessions/{sid}/resume", {"model": "local:web-test"})[0] == 200
    wait(worker, lambda w: sum(e["data"].get("type") == "done" for e in w.events) >= 2)
    assert web.sessions.workers[sid] is worker


@pytest.mark.slow
def test_approval_and_cancellation_through_the_protocol(web):
    (web.sessions.workspace / "web-result.txt").write_text("Original content\n")
    status, data = request(web, data={})
    assert status == 200, data
    sid = data["session_id"]
    worker = web.sessions.workers[sid]

    def questions(w):
        return [e["data"] for e in w.events if e["data"].get("type") == "input_requested"]

    def finished(w):
        return any(e["data"].get("type") == "done" for e in w.events)

    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "write a file"})[0] == 200
    wait(worker, lambda w: bool(questions(w)) or finished(w))
    if questions(worker):
        q = questions(worker)[0]
        # An unknown id goes to the worker, which answers with an error frame.
        assert request(web, f"/api/sessions/{sid}/answer", {"request_id": "unknown", "value": "yes"})[0] == 200
        wait(worker, lambda w: any("answer rejected" in str(e["data"].get("message")) for e in w.events))
        answer = {"request_id": q["request_id"], "value": q["choices"][0]}
        assert request(web, f"/api/sessions/{sid}/answer", answer)[0] == 200
    wait(worker, finished)
    assert (web.sessions.workspace / "web-result.txt").read_text() == "Web works\n"
    # No artifact endpoint: the write renders from its tool events.
    assert request(web, f"/api/sessions/{sid}/artifacts/write-1")[0] == 404
    assert any(e["data"].get("event") == "tool_execution_completed" for e in worker.events)
    done = sum(e["data"].get("type") == "done" for e in worker.events)
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "slow task"})[0] == 200
    assert request(web, f"/api/sessions/{sid}/cancel", {})[0] == 200
    wait(worker, lambda w: sum(e["data"].get("type") == "done" for e in w.events) > done)


@pytest.mark.slow
def test_tui_owner_cannot_be_resumed(web):
    sid = str(uuid.uuid4())
    register_active(sid, workspace=web.sessions.workspace, kind="tui")
    try:
        with pytest.raises(RuntimeError, match="owned"):
            web.sessions.resume(sid)
        assert sid not in web.sessions.workers or not web.sessions.workers[sid].alive
        # The lifetime lock also closes the check/register race across processes.
        command = (
            "from coding_agent.addons.persistence import register_active; register_active(%r, workspace='.', kind='web')"
            % sid
        )
        result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True)
        assert result.returncode != 0 and "owned" in result.stderr
    finally:
        release_active()
    assert web.sessions.resume(sid) == sid


@pytest.mark.slow
def test_historical_web_sessions_come_from_session_frames(web):
    from coding_agent.addons.persistence import JsonlPersistence, sessions_dir
    from core_ai.types import Message

    sid = str(uuid.uuid4())
    store = JsonlPersistence(sessions_dir(web.sessions.workspace, client="web"))
    store.client = "web"
    asyncio.run(store.save_conversation(session_id=sid, messages=[Message(role="user", content="Historical web task")]))
    listing = request(web)[1]
    assert any(s["session_id"] == sid and s["client"] == "web" for s in listing)
    assert request(web, f"/api/sessions/{sid}")[1]["messages"][0]["content"] == "Historical web task"


def test_cli_web_dispatch(monkeypatch):
    from coding_agent.cli import main

    calls = []
    monkeypatch.setattr(sys, "argv", ["symphony", "web", "--no-browser"])
    monkeypatch.setattr("coding_agent.web.server.main", lambda args: calls.append(args) or 0)
    with pytest.raises(SystemExit) as exit:
        main()
    assert exit.value.code == 0 and calls == [["--no-browser"]]


@pytest.mark.slow
def test_browser_refresh_streaming_and_approval(web):
    """Run with the CI-installed Chromium or the system browser."""
    import shutil
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        chromium = shutil.which("chromium") or shutil.which("chromium-browser")
        if chromium is None:
            chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            chromium = str(chrome) if chrome.is_file() else None
        if chromium is None:
            pytest.skip("chromium or Google Chrome is required for the browser test")
        browser = playwright.chromium.launch(executable_path=chromium, chromium_sandbox=True)
        page = browser.new_page()
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{web.origin}/#{web.token}")
        # SDK layout tokens must not stack the main panel below the sidebar.
        sidebar_box = page.locator('[data-slot="sidebar-container"]').bounding_box()
        main_box = page.locator("main").bounding_box()
        assert sidebar_box and main_box
        assert main_box["y"] == sidebar_box["y"] == 0
        assert main_box["x"] >= sidebar_box["x"] + sidebar_box["width"] - 1
        (web.sessions.workspace / "web-result.txt").write_text("Original content\n")
        # The chat SDK composer starts a session with its first prompt.
        page.get_by_label("Coding task").fill("write a file")
        page.get_by_role("button", name="Send message", exact=True).click()
        # A live session shows its model in the header and no reconnecting badge.
        expect(page.locator(".topbar .model")).to_contain_text("web-test")
        expect(page.get_by_text("reconnecting…", exact=True)).to_have_count(0)
        # Overwriting the pre-existing file must require human confirmation.
        # The HTTP test checks structured approval correlation; interact with
        # the real question here using its published accessible controls.
        worker = next(iter(web.sessions.workers.values()))
        def questions(w):
            return [e["data"] for e in w.events if e["data"].get("type") == "input_requested"]

        wait(worker, lambda w: bool(questions(w)) or any(e["data"].get("type") == "done" for e in w.events))
        if questions(worker):
            q = questions(worker)[0]
            # An approval renders one button per choice; a click sends the answer frame.
            expect(page.get_by_role("region", name="Approval required")).to_be_visible()
            page.get_by_role("button", name=q["choices"][0], exact=True).click()
        expect(page.get_by_text("Web task completed", exact=True)).to_be_visible(timeout=15000)
        page.reload()
        expect(page.get_by_text("Web task completed", exact=True)).to_be_visible()
        expect(page.locator(".topbar .model")).to_contain_text("web-test")
        expect(page.get_by_text("reconnecting…", exact=True)).to_have_count(0)
        page.get_by_label("Coding task").fill("second turn")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_text("Web task completed", exact=True)).to_have_count(2, timeout=15000)
        page.get_by_role("button", name="Refresh sessions", exact=True).click()
        search = page.get_by_label("Search sessions")
        search.fill("no matching session")
        expect(page.get_by_text("No matching sessions", exact=True)).to_be_visible()
        page.get_by_role("button", name="Clear search", exact=True).click()
        page.get_by_role("button", name="Pin write a file", exact=True).click()
        expect(page.get_by_role("region", name="Pinned")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        menu = page.get_by_role("button", name="Open session navigation", exact=True)
        menu.click()
        drawer = page.get_by_role("dialog")
        expect(drawer.get_by_label("Search sessions")).to_be_visible()
        page.keyboard.press("Escape")
        expect(drawer).to_have_count(0)
        expect(menu).to_be_focused()
        assert not failures
        browser.close()


def test_persistence_honors_configured_symphony_home(tmp_path, monkeypatch):
    from coding_agent.addons.persistence import active_dir, sessions_dir

    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path / "custom"))
    assert sessions_dir(client="tui") == tmp_path / "custom" / "tui" / "sessions"
    assert active_dir() == tmp_path / "custom" / "active"


def test_cli_opens_browser(monkeypatch, tmp_path, static):
    from types import SimpleNamespace
    from coding_agent.web import server

    opened = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    monkeypatch.setattr(
        server.threading, "Timer", lambda delay, callback, args: SimpleNamespace(start=lambda: callback(*args), cancel=lambda: None)
    )
    monkeypatch.setattr(server.Server, "serve_forever", lambda self: None)
    monkeypatch.setattr(server, "resolve_static", lambda root, **_: static)
    assert server.main(["--workspace", str(tmp_path)]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")
    assert len(opened[0].split("#")[1]) >= 32


@pytest.mark.slow
@pytest.mark.skipif(os.name == "nt", reason="POSIX terminal process-group signals")
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cli_shutdown_closes_workers_without_tracebacks(tmp_path, model, signum):
    # Run the actual CLI lifecycle with a control and a session worker, then
    # simulate Ctrl-C (the whole terminal group) or a process manager's SIGTERM.
    script = """
import sys
from pathlib import Path
from coding_agent.web import server
from coding_agent.web.sessions import Sessions
server.resolve_static = lambda root, **_: Path(sys.argv[1])
def warm(self):
    self.control()
    self.resume()
    print('WORKERS_READY', flush=True)
Sessions.warm = warm
raise SystemExit(server.main(['--no-browser', '--workspace', sys.argv[1], '--model', 'local:web-test']))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Bound startup as well as shutdown, and keep stderr in communicate so
        # the assertion catches tracebacks from inherited worker stderr too.
        ready = threading.Event()

        def read_startup():
            for line in process.stdout:
                if line.strip() == "WORKERS_READY":
                    ready.set()
                    return

        reader = threading.Thread(target=read_startup, daemon=True)
        reader.start()
        assert ready.wait(20), "Web workers did not start"
        reader.join(timeout=1)
        if signum == signal.SIGINT:
            os.killpg(process.pid, signum)
        else:
            process.send_signal(signum)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        assert stdout.splitlines().count("Goodbye!") == 1
        assert "Traceback" not in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_closed_sessions_reject_new_workers(tmp_path):
    from coding_agent.web.sessions import WorkerError

    sessions = Sessions(tmp_path)
    sessions.close()
    sessions.close()
    with pytest.raises(WorkerError, match="shutting down"):
        sessions.control()
    with pytest.raises(WorkerError, match="shutting down"):
        sessions.resume()


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def test_stage_attachments_validates_and_writes_images(tmp_path):
    assert stage_attachments(None, tmp_path) == []
    [path] = stage_attachments([{"media_type": "image/png", "data_url": f"data:image/png;base64,{PNG}"}], tmp_path)
    assert path.endswith(".png") and open(path, "rb").read().startswith(b"\x89PNG")
    for bad in (
        "nope",
        [{"media_type": "text/plain", "data_url": "data:text/plain;base64,aGk="}],
        [{"media_type": "image/png", "data_url": "data:image/jpeg;base64,aGk="}],
        [{"media_type": "image/png", "data_url": "data:image/png;base64,***"}],
        [{"media_type": "image/png", "data_url": f"data:image/png;base64,{PNG}"}] * 9,
    ):
        with pytest.raises(ValueError):
            stage_attachments(bad, tmp_path)
    assert len(list(tmp_path.iterdir())) == 1


def test_prompt_images_reach_the_run_frame_as_paths(web):
    status, data = request(web, data={})
    assert status == 200, data
    sid = data["session_id"]
    worker = web.sessions.workers[sid]
    bad = {"prompt": "look", "attachments": [{"media_type": "image/svg+xml", "data_url": "data:,"}]}
    assert request(web, f"/api/sessions/{sid}/prompt", bad)[0] == 400
    image = {"media_type": "image/png", "data_url": f"data:image/png;base64,{PNG}", "filename": "a.png"}
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "look", "attachments": [image]})[0] == 200
    wait(worker, lambda w: any(e["data"].get("type") == "done" for e in w.events))
    assert not any(e["data"].get("type") == "error" for e in worker.events)
    assert len(list(web.uploads.iterdir())) == 1


def test_model_registry_takes_the_provider_from_the_model_rows() -> None:
    catalog = registry({
        "default": "gw:vendor/model",
        "models": [
            {"id": "local:small", "label": "Small", "provider": "local", "context_limit": None},
            # The row's provider is the API route, not the id's prefix.
            {"id": "gw:vendor/model", "label": "Model", "provider": "gateway", "context_limit": 128000},
        ],
    })
    assert catalog["defaultProviderId"] == "gateway"
    [local, gateway] = catalog["providers"]
    assert gateway["defaultModel"] == "gw:vendor/model"
    assert gateway["models"] == [{"id": "gw:vendor/model", "label": "Model", "contextWindow": 128000}]
    assert local["models"] == [{"id": "local:small", "label": "Small"}]



def artifact_request(web, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", web.server_port, timeout=10)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, response.headers, body


def test_artifact_files_are_sandboxed_and_cannot_traverse(tmp_path, static):
    server = Server(("127.0.0.1", 0), Sessions(tmp_path), static)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        site = tmp_path / "site"
        site.mkdir()
        (site / "index.html").write_text("<script>document.title='x'</script>")
        (site / "app.css").write_text("body{}")
        sid = str(uuid.uuid4())
        saved = ArtifactStore(sessions_dir(tmp_path, client="web")).save(sid, snapshot_path(site, tmp_path), "c1")
        assert saved is not None
        base = f"/artifacts/{server.artifact_token}/{sid}/{saved.manifest.id}"

        status, headers, body = artifact_request(server, f"{base}/v1/index.html", {"Sec-Fetch-Site": "cross-site"})
        assert status == 200 and body.startswith(b"<script>")
        assert headers["Content-Type"] == "text/html"
        policy = headers["Content-Security-Policy"]
        assert policy.startswith("sandbox allow-scripts;") and "allow-same-origin" not in policy
        assert f"frame-ancestors {server.origin}" in policy and "connect-src 'none'" in policy
        assert artifact_request(server, f"{base}/v1/app.css")[1]["Content-Type"] == "text/css"

        (tmp_path / "secret.txt").write_text("secret")
        for path in [
            f"{base}/v1/../../../../../secret.txt",
            f"{base}/v1/%2e%2e/%2e%2e/manifest.json/../../x",
            f"{base}/v1",
            f"/artifacts/{server.artifact_token}/{sid}/..%2f..%2f/v1/index.html",
        ]:
            assert artifact_request(server, path)[0] in {400, 403, 404}, path
        assert artifact_request(server, f"/artifacts/{server.token}/{sid}/{saved.manifest.id}/v1/index.html")[0] == 403
        assert artifact_request(server, f"{base}/v1/index.html", {"Host": "evil.example"})[0] == 403
        assert artifact_request(server, f"/artifacts/{server.artifact_token}/not-a-uuid/x/v1/a")[0] == 400
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.slow
def test_session_artifacts_come_from_the_worker(web):
    status, created = request(web, "/api/sessions", {})
    sid = created["session_id"]
    assert request(web, f"/api/sessions/{sid}/prompt", {"prompt": "write a csv"})[0] == 200
    worker = web.sessions.workers[sid]
    wait(worker, lambda w: any(e["data"].get("event") == "artifact_created" for e in w.events))
    status, listed = request(web, f"/api/sessions/{sid}/artifacts")
    assert status == 200 and listed["base"] == f"/artifacts/{web.artifact_token}/{sid}"
    [artifact] = listed["artifacts"]
    assert (artifact["kind"], artifact["title"], artifact["entry"]) == ("csv", "table.csv", "v1/table.csv")
    status, _, body = artifact_request(web, f"{listed['base']}/{artifact['id']}/{artifact['entry']}")
    assert status == 200 and body == b"a,b\n1,2\n"
    assert request(web, f"/api/sessions/{sid}/artifacts", headers={"X-Symphony-Token": "bad"})[0] == 403
