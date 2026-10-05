"""Line-delimited JSON transport for external agent managers.

Only protocol frames go to stdout. Each process handles one turn; later turns
resume the persisted Symphony session by its id.

``transport`` writes frames, ``catalog`` answers model lists, and ``server``
runs the command loop. The names below stay on this package because hosts and
tests patch them here.
"""

import sys

from coding_agent.agent import build_agent
from coding_agent.credentials import load_provider_env
from coding_agent.protocols.stdio.catalog import model_catalog
from coding_agent.protocols.stdio.server import main, serve
from coding_agent.protocols.stdio.transport import (
    CAPABILITIES,
    PROTOCOL_VERSION,
    StdioSink,
    user_content,
    write_frame,
)

__all__ = [
    "CAPABILITIES",
    "PROTOCOL_VERSION",
    "StdioSink",
    "build_agent",
    "load_provider_env",
    "main",
    "model_catalog",
    "serve",
    "sys",
    "user_content",
    "write_frame",
]
