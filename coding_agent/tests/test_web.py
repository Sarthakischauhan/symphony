"""Exercise HTTP policy, historical storage, and the real agent worker transport."""

import asyncio
import http.client
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from coding_agent.addons.persistence import register_active, release_active
from coding_agent.web.bundle import resolve_static
from coding_agent.web.server import Server
from coding_agent.web.sessions import Sessions


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
                                "arguments": json.dumps({"path": "web-result.txt", "content": "Web works\n"}),
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


def test_warm_starts_the_control_worker_before_any_request(web):
    assert web.sessions._control is None
    web.sessions.warm()
    deadline = time.monotonic() + 15
    while web.sessions._control is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert web.sessions._control is not None and web.sessions._control.alive
    status, info = request(web, "/api/info")
    assert status == 200 and info["path"] == str(web.sessions.workspace)


def test_workspace_info_models_and_commands_come_from_the_worker(web):
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "web-branch", str(web.sessions.workspace)], check=True)
    web.sessions.close()
    web.sessions._control = None
    status, info = request(web, "/api/info")
    assert status == 200, info
    # Workspace and branch arrive in the worker's ready frame.
    assert info["path"] == str(web.sessions.workspace) and info["name"] == web.sessions.workspace.name
    assert info["branch"] == "web-branch"
    status, catalog = request(web, "/api/models")
    assert status == 200, catalog
    # The chat SDK registry shape, built from the worker's model/list reply.
    assert catalog["defaultProviderId"] == "local"
    local = next(p for p in catalog["providers"] if p["id"] == "local")
    assert any(m["id"] == "local:web-test" for m in local["models"])
    status, commands = request(web, "/api/commands")
    assert status == 200 and any(item["name"] == "help" for item in commands)


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
    from coding_agent.tui.__main__ import main

    calls = []
    monkeypatch.setattr(sys, "argv", ["symphony", "web", "--no-browser"])
    monkeypatch.setattr("coding_agent.web.server.main", lambda args: calls.append(args) or 0)
    with pytest.raises(SystemExit) as exit:
        main()
    assert exit.value.code == 0 and calls == [["--no-browser"]]


def test_browser_refresh_streaming_and_approval(web):
    """Run with the CI-installed Chromium or the system browser."""
    import shutil
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=shutil.which("chromium"), chromium_sandbox=True)
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
        expect(page.get_by_text("Connected", exact=True)).to_be_visible()
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
        expect(page.get_by_text("Connected", exact=True)).to_be_visible()
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
        server.threading, "Timer", lambda delay, callback, args: SimpleNamespace(start=lambda: callback(*args))
    )
    monkeypatch.setattr(server.Server, "serve_forever", lambda self: None)
    monkeypatch.setattr(server, "resolve_static", lambda root: static)
    assert server.main(["--workspace", str(tmp_path)]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")
    assert len(opened[0].split("#")[1]) >= 32
