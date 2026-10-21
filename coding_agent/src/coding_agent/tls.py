"""TLS for the standard-library HTTPS calls: the PyPI update check and the
Symphony Web bundle download.

uv-managed Pythons on macOS ship an OpenSSL whose default CA path does not
exist, so ``urllib`` cannot verify PyPI or GitHub there. The context keeps the
default trust (including ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``) and adds
certifi's bundle, which httpx already uses for provider requests.
"""

from __future__ import annotations

import ssl
from functools import cache

import certifi


@cache
def https_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


__all__ = ["https_context"]
