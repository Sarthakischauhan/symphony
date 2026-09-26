"""Local catalog the demo drives. No network, no login wall, nothing on disk."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOOKSTORE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Symphony Books</title>
</head>
<body>
  <h1>Symphony Books</h1>
  <p>Search the catalog.</p>
  <form id="search" action="javascript:void(0)">
    <input id="q" type="text" aria-label="Search books" placeholder="Search books">
    <button id="go" type="submit">Search</button>
  </form>
  <ul id="results"></ul>
  <script>
    const books = [
      { title: "The Alps Guide", price: "$18", blurb: "A travel guide to alpine huts." },
      { title: "Kernel Craft", price: "$24", blurb: "Notes on operating systems." }
    ];
    function render() {
      const query = document.getElementById("q").value.toLowerCase();
      const hits = books.filter((book) =>
        (book.title + " " + book.blurb).toLowerCase().includes(query)
      );
      const list = document.getElementById("results");
      list.innerHTML = hits.length
        ? hits.map((book) =>
            "<li><strong>" + book.title + "</strong> — " + book.price + " — " + book.blurb + "</li>"
          ).join("")
        : "<li>No matches.</li>";
    }
    document.getElementById("search").addEventListener("submit", (event) => {
      event.preventDefault();
      render();
    });
  </script>
</body>
</html>
"""

DEMO_GOAL = "Search for travel and report the price of The Alps Guide."


class _QuietHandler(BaseHTTPRequestHandler):
    """Answers every GET with ``BOOKSTORE_HTML`` and logs nothing."""

    def do_GET(self) -> None:
        body = BOOKSTORE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class DemoSite:
    """Serves the catalog on an ephemeral 127.0.0.1 port until ``close``."""

    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        """The catalog's root URL."""
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/"

    def close(self) -> None:
        """Stop serving and release the port."""
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


__all__ = ["BOOKSTORE_HTML", "DEMO_GOAL", "DemoSite"]
