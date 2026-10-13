"""Agent Client Protocol host for editors and other ACP clients.

``mapping`` translates events and questions, ``transport`` is JSON-RPC over
stdio, and ``server`` runs the sessions. The names below stay on this package
because tests patch them here.
"""

import sys

from coding_agent.agent import build_agent
from coding_agent.config.credentials import load_provider_env
from coding_agent.protocols.acp.mapping import PROTOCOL_VERSION
from coding_agent.protocols.acp.server import AcpSink, Server, main, serve
from coding_agent.protocols.acp.transport import Connection, write_message

__all__ = [
    "AcpSink",
    "Connection",
    "PROTOCOL_VERSION",
    "Server",
    "build_agent",
    "load_provider_env",
    "main",
    "serve",
    "sys",
    "write_message",
]
