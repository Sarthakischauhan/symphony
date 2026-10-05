"""Host protocols. The stdio JSONL transport lives in ``protocols.stdio``."""

from coding_agent.protocols.stdio import CAPABILITIES, PROTOCOL_VERSION, StdioSink, main, serve

__all__ = ["CAPABILITIES", "PROTOCOL_VERSION", "StdioSink", "main", "serve"]
