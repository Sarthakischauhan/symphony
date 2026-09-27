"""Backward-compatible import path for ``symphony-browser``'s entry point."""

from browser_agent.run.cli import build_parser, main

__all__ = ["build_parser", "main"]
