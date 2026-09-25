"""Local catalog the demo drives. No network, no login wall."""

from __future__ import annotations

import functools
import shutil
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


class DemoSite:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="symphony-browser-"))
        (self.root / "index.html").write_text(BOOKSTORE_HTML, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=str(self.root))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


__all__ = ["BOOKSTORE_HTML", "DEMO_GOAL", "DemoSite"]
