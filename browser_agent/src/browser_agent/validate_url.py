"""The browser opens web pages only: http or https, with a host."""

from __future__ import annotations

from urllib.parse import urlsplit


def require_http_url(url: str) -> None:
    """Raise ValueError unless ``url`` is http or https with a host."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Only http and https URLs with a host are allowed, got {url!r}.")


__all__ = ["require_http_url"]
