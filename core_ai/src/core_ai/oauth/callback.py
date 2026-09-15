from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

SUCCESS_HTML = """<!doctype html>
<html><body style="font-family:sans-serif;background:#111;color:#eee;padding:2rem">
<h1>Symphony</h1>
<p>Signed in. You can close this tab and return to the terminal.</p>
</body></html>
"""

ERROR_HTML = """<!doctype html>
<html><body style="font-family:sans-serif;background:#111;color:#eee;padding:2rem">
<h1>Symphony</h1>
<p>Sign-in did not finish. Return to the terminal and try again.</p>
</body></html>
"""


class CallbackServer(ThreadingHTTPServer):
    expected_path: str
    on_result: Callable[[str, str, str], None]


def start_callback_server(
    host: str,
    port: int,
    path: str,
    on_result: Callable[[str, str, str], None],
) -> CallbackServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") != path.rstrip("/") and parsed.path != path:
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            error = (query.get("error_description") or query.get("error") or [""])[0]
            body = ERROR_HTML if error or not code else SUCCESS_HTML
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            self.server.on_result(code, state, error)

    server = CallbackServer((host, port), Handler)
    server.expected_path = path
    server.on_result = on_result
    return server
