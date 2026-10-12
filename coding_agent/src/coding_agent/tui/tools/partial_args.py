"""Read string values out of tool-call JSON that may still be streaming."""

from __future__ import annotations

import json
import re
from typing import Optional


def string_field(raw: str, key: str) -> Optional[str]:
    """Decoded value of the first complete ``"key": "..."`` string in ``raw``.

    ``raw`` may be a partial JSON blob, so this does not parse the whole
    document. Returns None when no complete string value for ``key`` exists.
    """
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', raw)
    if match is None:
        return None
    return json.loads(f'"{match.group(1)}"')
