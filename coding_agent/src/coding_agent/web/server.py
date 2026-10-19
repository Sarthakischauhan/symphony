"""Dependency-free loopback HTTP commands and ordered, replayable SSE events."""

import argparse
import json
import secrets
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from coding_agent.commands.catalog import EFFORTS
from coding_agent.web.sessions import Sessions

STATIC = Path(__file__).with_name("static")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, sessions):
        self.sessions = sessions
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def handle_error(self, request, client_address):
        # Browsers drop idle keep-alive connections (reloads, closed streams);
        # http.server reads the next request line outside the handler's try.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def server_close(self):
        self.sessions.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # URLs may contain the per-launch capability token.

    def _guard(self, mutation=False):
        # Exact Host stops DNS rebinding. Origin + Fetch Metadata + a random
        # capability stop cross-site requests, including form and SSE requests.
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            raise PermissionError("Invalid Host")
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            raise PermissionError("Invalid Origin")
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            raise PermissionError("Cross-site request denied")
        if mutation and self.headers.get("Content-Type") != "application/json":
            raise PermissionError("JSON content type required")
        if urlsplit(self.path).path.startswith("/api/"):
            supplied = self.headers.get("X-Symphony-Token") or parse_qs(urlsplit(self.path).query).get("token", [""])[0]
            if not secrets.compare_digest(supplied, self.server.token):
                raise PermissionError("Invalid capability")

    def _headers(self, status, content_type, length=None):
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

    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self._headers(status, "application/json", len(body))
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._guard()
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            if path == "/api/sessions":
                return self._json(self.server.sessions.listing())
            if path == "/api/info":
                return self._json(self.server.sessions.info())
            if path == "/api/models":
                return self._json(self.server.sessions.models())
            if len(parts) >= 3 and parts[:2] == ["api", "sessions"]:
                session_id = str(uuid.UUID(parts[2]))
                worker = self.server.sessions.workers.get(session_id)
                if len(parts) == 5 and parts[3] == "artifacts":
                    asset = worker.artifacts.get(unquote(parts[4])) if worker else None
                    if asset is None or not asset.resolve().is_relative_to(self.server.sessions.workspace):
                        raise ValueError("Unknown artifact")
                    body = asset.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", "attachment")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if len(parts) == 4 and parts[3] == "events":
                    if worker is None:
                        return self._json({"error": "Resume session first"}, 409)
                    query = parse_qs(urlsplit(self.path).query)
                    cursor = int(self.headers.get("Last-Event-ID") or query.get("after", ["0"])[0])
                    if cursor < 0 or cursor > len(worker.events):
                        return self._json({"error": "Invalid event cursor; reload session"}, 409)
                    self._headers(200, "text/event-stream")
                    while True:
                        with worker.condition:
                            worker.condition.wait_for(lambda: len(worker.events) > cursor, timeout=10)
                            batch = worker.events[cursor:]
                        for event in batch:
                            self.wfile.write(f"id: {event['id']}\ndata: {json.dumps(event['data'])}\n\n".encode())
                            cursor = event["id"]
                        if not batch:
                            self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        if worker.process.poll() is not None and cursor == len(worker.events):
                            return
                if len(parts) != 3:
                    return self._json({"error": "Not found"}, 404)
                alive = worker is not None and worker.process.poll() is None
                history = worker.baseline if alive else self.server.sessions.history(session_id)
                return self._json({**history, "owned": alive, "model": worker.model if alive else ""})
            if path.startswith("/api/"):
                return self._json({"error": "Not found"}, 404)
            asset = (STATIC / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not asset.is_relative_to(STATIC.resolve()) or not asset.is_file():
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
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        try:
            self._guard(mutation=True)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 * 1024:
                raise ValueError("Request must be between 1 byte and 1 MiB")
            self.connection.settimeout(30)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            parts = urlsplit(self.path).path.strip("/").split("/")
            sessions = self.server.sessions
            model = data.get("model")
            if model is not None and (not isinstance(model, str) or not 0 < len(model) <= 200):
                raise ValueError("Invalid model")
            if parts == ["api", "sessions"]:
                return self._json({"session_id": sessions.resume(model=model)})
            if len(parts) != 4 or parts[:2] != ["api", "sessions"]:
                return self._json({"error": "Not found"}, 404)
            session_id = str(uuid.UUID(parts[2]))
            if parts[3] == "resume":
                known = {item["session_id"] for item in sessions.listing()} | sessions.workers.keys()
                if session_id not in known:
                    raise ValueError("Unknown session")
                return self._json({"session_id": sessions.resume(session_id, model)})
            worker = sessions.workers.get(session_id)
            if worker is None:
                raise RuntimeError("Resume session first")
            if parts[3] == "prompt":
                if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
                    raise ValueError("A prompt is required")
                command = {"type": "run", "prompt": data["prompt"]}
                effort = data.get("reasoning_effort")
                if effort is not None:
                    if effort not in EFFORTS:
                        raise ValueError("Unsupported reasoning effort")
                    command["reasoning_effort"] = effort
                # The worker protocol rejects overlapping turns. Serialize the
                # command and busy check here so two tabs cannot race.
                with worker.condition:
                    if worker.busy:
                        raise RuntimeError("Session is already running")
                    worker.busy = True
                    try:
                        worker.command(command)
                    except Exception:
                        worker.busy = False
                        raise
                    worker.append({"type": "user", "text": data["prompt"]})
            elif parts[3] == "cancel":
                worker.command({"type": "interrupt"})
            elif parts[3] == "answer":
                with worker.condition:
                    request_id = data.get("request_id")
                    if (
                        not isinstance(request_id, str)
                        or request_id not in worker.pending
                        or not isinstance(data.get("value"), str)
                    ):
                        raise ValueError("Unknown approval request or invalid answer")
                    worker.command({"type": "answer", "request_id": request_id, "value": data["value"]})
                    worker.append({"type": "answered", "request_id": request_id})
            else:
                return self._json({"error": "Not found"}, 404)
            self._json({"ok": True})
        except PermissionError as exc:
            self._json({"error": str(exc)}, 403)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="symphony web", description="Run Symphony in your local browser")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--port", type=int, default=0, help="Local port (default: choose a free port)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not (STATIC / "index.html").is_file():
        parser.error("Web assets missing. Contributors: run npm ci && npm run build in coding_agent/web-ui")
    server = Server(("127.0.0.1", args.port), Sessions(Path(args.workspace).expanduser().resolve(), args.model))
    print(f"Symphony Web listening on {server.origin}", flush=True)
    # Capability stays in the URL fragment, never in the HTTP request or logs.
    if not args.no_browser:
        threading.Timer(0.2, webbrowser.open, args=[f"{server.origin}/#{server.token}"]).start()
    else:
        print(f"Open {server.origin}/#{server.token} in a trusted local browser", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
