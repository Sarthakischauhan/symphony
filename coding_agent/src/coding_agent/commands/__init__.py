"""Slash-command catalog shared by the TUI and the stdio host.

Pure data and matching. Nothing here imports Textual, so headless surfaces
(``protocols/stdio``) can read the same catalog the TUI shows.
"""
