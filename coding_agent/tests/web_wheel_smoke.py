"""Run with an isolated wheel environment's Python, without source path injection."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import sysconfig
import tempfile
import time
import urllib.request


class LocalModels(BaseHTTPRequestHandler):
    """A local OpenAI-compatible provider, so the stdio worker can start."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "smoke"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    models = ThreadingHTTPServer(("127.0.0.1", 0), LocalModels)
    threading.Thread(target=models.serve_forever, daemon=True).start()
    provider = {"LOCAL_BASE_URL": f"http://127.0.0.1:{models.server_port}/v1", "LOCAL_MODEL": "smoke"}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    str(Path(sysconfig.get_path("scripts")) / "symphony"),
                    "web",
                    "--no-browser",
                    "--workspace",
                    directory,
                ],
                env={**os.environ, **provider, "SYMPHONY_HOME": str(root / "symphony")},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                match = None
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"Open (http://[^#]+)#([^ ]+) in", output)
                    if match:
                        break
                    if process.poll() is not None:
                        raise RuntimeError("Installed symphony web exited before startup")
                    time.sleep(0.05)
                assert match, "Installed symphony web did not become ready"
                url, token = match.groups()
                with urllib.request.urlopen(url) as response:
                    html = response.read().decode()
                    assert response.status == 200 and "Symphony Web" in html
                script = re.search(r'src="([^"]+\.js)"', html)
                assert script, "Wheel omitted the frontend entry script"
                with urllib.request.urlopen(url.rstrip("/") + script[1]) as response:
                    assert response.status == 200 and len(response.read()) > 1000
                request = urllib.request.Request(url + "api/sessions", headers={"X-Symphony-Token": token})
                # Sessions come from the installed stdio worker's session/list frame.
                with urllib.request.urlopen(request, timeout=60) as response:
                    assert response.status == 200 and json.load(response) == []
                print("Installed wheel: CLI, HTTP server, compiled JavaScript, and session API passed")
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
