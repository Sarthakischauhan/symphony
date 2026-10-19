"""Dependency-free loopback HTTP commands and ordered, replayable SSE events."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import secrets
import shutil
import signal
import socket
import sys
import tempfile
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from coding_agent.web.bundle import BundleError, bundle_root, install, resolve_static, rollback
from coding_agent.web.sessions import JsonObject, Sessions, WorkerError


# The stdio run frame takes at most 8 images of under 20 MiB each.
MAX_ATTACHMENTS = 8
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# Base64 grows 4/3; a prompt may carry every image plus its text.
PROMPT_LIMIT = MAX_ATTACHMENTS * (MAX_IMAGE_BYTES * 4 // 3 + 1024) + 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def stage_attachments(raw: object, folder: Path) -> list[str]:
    """Write composer images (data URLs) to files; the run frame takes host paths."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENTS:
        raise ValueError(f"attachments must be a list of at most {MAX_ATTACHMENTS} images")
    decoded: list[tuple[str, bytes]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each attachment must be an object")
        media_type, data_url = item.get("media_type"), item.get("data_url")
        if not isinstance(media_type, str) or media_type not in IMAGE_TYPES:
            raise ValueError("Attachments must be PNG, JPEG, GIF or WebP images")
        prefix = f"data:{media_type};base64,"
        if not isinstance(data_url, str) or not data_url.startswith(prefix):
            raise ValueError("Attachment data must be a base64 data URL of its media type")
        try:
            data = base64.b64decode(data_url[len(prefix) :], validate=True)
        except binascii.Error as exc:
            raise ValueError("Attachment data is not valid base64") from exc
        if not 0 < len(data) < MAX_IMAGE_BYTES:
            raise ValueError("Each image must be under 20 MiB")
        decoded.append((IMAGE_TYPES[media_type], data))
    paths: list[str] = []
    for suffix, data in decoded:
        path = folder / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], sessions: Sessions, static: Path) -> None:
        self.sessions = sessions
        self.static = static
        self.token = secrets.token_urlsafe(32)
        # Composer images live here until the server stops; workers read them by path.
        self.uploads = Path(tempfile.mkdtemp(prefix="symphony-web-uploads-"))
        super().__init__(address, Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def handle_error(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int],
    ) -> None:
        # Browsers drop idle keep-alive connections (reloads, closed streams);
        # http.server reads the next request line outside the handler's try.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def server_close(self) -> None:
        self.sessions.close()
        shutil.rmtree(self.uploads, ignore_errors=True)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass  # URLs may contain the per-launch capability token.

    @property
    def app(self) -> Server:
        server = self.server
        if not isinstance(server, Server):
            raise TypeError("Handler requires the Symphony Web server")
        return server

    def _guard(self, mutation: bool = False) -> None:
        # Exact Host stops DNS rebinding. Origin + Fetch Metadata + a random
        # capability stop cross-site requests, including form and SSE requests.
        if self.headers.get("Host") != urlsplit(self.app.origin).netloc:
            raise PermissionError("Invalid Host")
        origin = self.headers.get("Origin")
        if origin and origin != self.app.origin:
            raise PermissionError("Invalid Origin")
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            raise PermissionError("Cross-site request denied")
        if mutation and self.headers.get("Content-Type") != "application/json":
            raise PermissionError("JSON content type required")
        if urlsplit(self.path).path.startswith("/api/"):
            supplied = self.headers.get("X-Symphony-Token") or parse_qs(urlsplit(self.path).query).get("token", [""])[0]
            if not secrets.compare_digest(supplied, self.app.token):
                raise PermissionError("Invalid capability")

    def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self._headers(status, "application/json", len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            self._guard()
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            if path == "/api/sessions":
                return self._json(self.app.sessions.listing())
            if path == "/api/info":
                return self._json(self.app.sessions.info())
            if path == "/api/models":
                return self._json(self.app.sessions.models())
            if path == "/api/commands":
                return self._json(self.app.sessions.commands())
            if len(parts) >= 3 and parts[:2] == ["api", "sessions"]:
                session_id = str(uuid.UUID(parts[2]))
                worker = self.app.sessions.workers.get(session_id)
                if len(parts) == 4 and parts[3] == "events":
                    if worker is None:
                        return self._json({"error": "Resume session first"}, 409)
                    query = parse_qs(urlsplit(self.path).query)
                    cursor = int(self.headers.get("Last-Event-ID") or query.get("after", ["0"])[0])
                    if cursor < 0 or cursor > len(worker.events):
                        return self._json({"error": "Invalid event cursor; reload session"}, 409)
                    self._headers(200, "text/event-stream")
                    live = worker
                    while True:
                        with live.condition:
                            live.condition.wait_for(lambda: len(live.events) > cursor, timeout=10)
                            batch = live.events[cursor:]
                        for event in batch:
                            self.wfile.write(f"id: {event['id']}\ndata: {json.dumps(event['data'])}\n\n".encode())
                            cursor = event["id"]
                        if not batch:
                            self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        if not live.alive and cursor == len(live.events):
                            return
                if len(parts) != 3:
                    return self._json({"error": "Not found"}, 404)
                owned = self.app.sessions.owned(session_id)
                if owned is None:
                    return self._json({**self.app.sessions.history(session_id), "owned": False, "model": ""})
                baseline = self.app.sessions.baselines.get(session_id, {})
                return self._json({**baseline, "owned": True, "model": owned.ready.model})
            if path.startswith("/api/"):
                return self._json({"error": "Not found"}, 404)
            static = self.app.static.resolve()
            asset = (static / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not asset.is_relative_to(static) or not asset.is_file():
                return self._json({"error": "Not found"}, 404)
            types = {
                ".html": "text/html",
                ".js": "text/javascript",
                ".css": "text/css",
                ".svg": "image/svg+xml",
                ".woff2": "font/woff2",
            }
            body = asset.read_bytes()
            self._headers(200, types.get(asset.suffix, "application/octet-stream"), len(body))
            self.wfile.write(body)
        except PermissionError as exc:
            self._json({"error": str(exc)}, 403)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
        except WorkerError as exc:
            self._json({"error": str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            self._guard(mutation=True)
            parts = urlsplit(self.path).path.strip("/").split("/")
            length = int(self.headers.get("Content-Length", "0"))
            # Only a prompt may carry images; every other command stays small.
            limit = PROMPT_LIMIT if parts[-1:] == ["prompt"] else 1024 * 1024
            if not 0 < length <= limit:
                raise ValueError(f"Request must be between 1 byte and {limit // (1024 * 1024)} MiB")
            self.connection.settimeout(30)
            data: object = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            sessions = self.app.sessions
            model = data.get("model")
            if model is not None and (not isinstance(model, str) or not 0 < len(model) <= 200):
                raise ValueError("Invalid model")
            if parts == ["api", "sessions"]:
                sid = sessions.resume(model=model)
                return self._json({"session_id": sid, "model": sessions.model_of(sid)})
            if len(parts) != 4 or parts[:2] != ["api", "sessions"]:
                return self._json({"error": "Not found"}, 404)
            session_id = str(uuid.UUID(parts[2]))
            if parts[3] == "resume":
                known = {str(item.get("session_id")) for item in sessions.listing()} | sessions.workers.keys()
                if session_id not in known:
                    raise ValueError("Unknown session")
                sid = sessions.resume(session_id, model)
                return self._json({"session_id": sid, "model": sessions.model_of(sid)})
            worker = sessions.owned(session_id)
            if worker is None:
                raise WorkerError("Resume session first")
            if parts[3] == "prompt":
                prompt = data.get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    raise ValueError("A prompt is required")
                command: JsonObject = {"type": "run", "prompt": prompt}
                attachments = stage_attachments(data.get("attachments"), self.app.uploads)
                if attachments:
                    command["attachments"] = attachments
                effort = data.get("reasoning_effort")
                if isinstance(effort, str):
                    # The worker validates the effort and rejects overlapping runs.
                    command["reasoning_effort"] = effort
                worker.command(command)
            elif parts[3] == "cancel":
                worker.command({"type": "interrupt"})
            elif parts[3] == "answer":
                request_id, value = data.get("request_id"), data.get("value")
                if not isinstance(request_id, str) or not isinstance(value, str):
                    raise ValueError("An answer needs a request_id and a value")
                # The worker rejects ids with no waiting question.
                worker.command({"type": "answer", "request_id": request_id, "value": value})
            else:
                return self._json({"error": "Not found"}, 404)
            self._json({"ok": True})
        except PermissionError as exc:
            self._json({"error": str(exc)}, 403)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
        except WorkerError as exc:
            self._json({"error": str(exc)}, 409)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="symphony web", description="Run Symphony in your local browser")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--port", type=int, default=0, help="Local port (default: choose a free port)")
    parser.add_argument("--no-browser", action="store_true")
    assets = parser.add_mutually_exclusive_group()
    assets.add_argument(
        "--update",
        action="store_true",
        help="Download and switch to the web assets for the installed symphony-code (or --bundle-version), then exit",
    )
    assets.add_argument("--rollback", action="store_true", help="Switch back to the previous web assets, then exit")
    parser.add_argument("--bundle-version", help="Release to install with --update (default: installed symphony-code)")
    args = parser.parse_args(argv)
    root = bundle_root()
    try:
        if args.update:
            from coding_agent.updates import installed_version

            version = args.bundle_version or installed_version()
            if version is None:
                parser.error("cannot tell the installed symphony-code release; pass --bundle-version")
            print(f"Symphony Web {version} installed in {install(version, root)}", flush=True)
            return 0
        if args.rollback:
            print(f"Symphony Web rolled back to {rollback(root)}", flush=True)
            return 0
        static = resolve_static(root)
    except BundleError as exc:
        print(f"symphony web: error: {exc}", file=sys.stderr, flush=True)
        return 1
    server = Server(
        ("127.0.0.1", args.port), Sessions(Path(args.workspace).expanduser().resolve(), args.model), static
    )
    print(f"Symphony Web listening on {server.origin}", flush=True)

    def terminate(signum: int, frame: object) -> None:
        # shutdown() cannot run on the serve_forever thread: it would deadlock.
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    browser_timer = None
    try:
        server.sessions.warm()
        # Capability stays in the URL fragment, never in the HTTP request or logs.
        if not args.no_browser:
            browser_timer = threading.Timer(0.2, webbrowser.open, args=[f"{server.origin}/#{server.token}"])
            browser_timer.start()
        else:
            print(f"Open {server.origin}/#{server.token} in a trusted local browser", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("Goodbye!", flush=True)
    finally:
        try:
            if browser_timer is not None:
                browser_timer.cancel()
            server.server_close()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
    return 0
