"""Capture the images, html, csv and json files a run produces as artifacts.

``on_tool`` sees every successful tool call after it ran:

- ``write_file``, ``patch`` and ``generate_image`` capture the written path
  when its suffix is html, csv, json or an image (see ``capture``). A file
  inside a website folder (one below the workspace with ``index.html``)
  versions that whole site instead.
- ``save_artifact`` captures its path with the kind and title it was given.
- Any other tool except ``read_file`` captures the inline images it returned.

Each stored version is emitted through the session's harness as
``artifact/created`` or ``artifact/updated`` (the manifest plus the absolute
``path`` of its entry file), so it is journaled and reaches every host.
Unchanged content stores and emits nothing. Subagents inherit the add-on and
store into the parent session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Optional

from core_ai.content import normalize_content
from core_harness import Addon, CoreHarness
from core_harness.models import ToolCall, ToolResult

from coding_agent.addons.artifacts.capture import (
    SITE_ENTRY,
    ArtifactError,
    Snapshot,
    snapshot_image_part,
    snapshot_path,
    snapshot_site,
)
from coding_agent.addons.artifacts.kinds import ArtifactKind, kind_of
from coding_agent.addons.artifacts.store import ArtifactStore, Saved

ARTIFACT_CREATED = "artifact/created"
ARTIFACT_UPDATED = "artifact/updated"
PATH_TOOLS = frozenset({"write_file", "patch", "generate_image"})
SAVE_TOOL = "save_artifact"
# Reading an image shows an existing file; it produces nothing.
READ_TOOLS = frozenset({"read_file"})

logger = logging.getLogger(__name__)


def resolve(workspace: Path, raw: str) -> Path:
    """The path a workspace tool wrote, resolved the way ``WorkspaceTool`` does."""
    candidate = Path(raw.strip()).expanduser()
    return (candidate if candidate.is_absolute() else workspace / candidate).resolve()


def site_of(path: Path, workspace: Path) -> Path | None:
    """The nearest folder below the workspace holding ``index.html`` and ``path``.

    Writing any file of a website (its index.html, css, scripts or images)
    versions the whole site.
    """
    for folder in path.parents:
        if folder == workspace or not folder.is_relative_to(workspace):
            return None
        if (folder / SITE_ENTRY).is_file():
            return folder
    return None


def artifact_frame(store: ArtifactStore, session_id: str, saved: Saved) -> tuple[str, dict[str, object]]:
    manifest = saved.manifest
    entry = store.folder(session_id, manifest.id) / manifest.entry
    return (
        ARTIFACT_CREATED if saved.created else ARTIFACT_UPDATED,
        {**manifest.to_json(), "path": str(entry)},
    )


class ArtifactsAddon(Addon):
    name = "artifacts"

    def __init__(self, store: ArtifactStore, workspace: Path, owner: Optional[CoreHarness] = None) -> None:
        self.store = store
        self.workspace = Path(workspace).expanduser().resolve()
        # The harness whose session keeps the artifacts: the parent for subagents.
        self.owner = owner

    def attach(self, harness: Any) -> None:
        if self.owner is None and isinstance(harness, CoreHarness):
            self.owner = harness

    def fork_for_child(self, parent_harness: Any) -> Optional[Addon]:
        del parent_harness
        return ArtifactsAddon(self.store, self.workspace, self.owner)

    def snapshots(self, tool_call: ToolCall, result: ToolResult) -> Iterator[Snapshot]:
        arguments: Mapping[str, Any] = tool_call.arguments
        raw = arguments.get("path")
        if tool_call.name == SAVE_TOOL and isinstance(raw, str):
            title = arguments.get("title")
            yield snapshot_path(
                resolve(self.workspace, raw), self.workspace,
                ArtifactKind(str(arguments.get("kind"))), title if isinstance(title, str) else "",
            )
        elif tool_call.name in PATH_TOOLS and isinstance(raw, str):
            path = resolve(self.workspace, raw)
            site = site_of(path, self.workspace)
            if site is not None:
                yield snapshot_site(site, self.workspace)
            elif kind_of(path) is not None:
                yield snapshot_path(path, self.workspace)
        elif tool_call.name not in READ_TOOLS and not isinstance(result.content, str):
            for index, part in enumerate(normalize_content(result.content)):
                captured = snapshot_image_part(part, tool_call.id, index)
                if captured is not None:
                    yield captured

    async def on_tool(self, **payload: Any) -> None:
        tool_call, result, owner = payload.get("tool_call"), payload.get("result"), self.owner
        if not isinstance(tool_call, ToolCall) or not isinstance(result, ToolResult) or owner is None:
            return
        if result.status != "success" or not owner.session_id:
            return
        session_id = owner.session_id
        try:
            for captured in self.snapshots(tool_call, result):
                saved = await asyncio.to_thread(self.store.save, session_id, captured, tool_call.id)
                if saved is not None:
                    event, body = artifact_frame(self.store, session_id, saved)
                    await owner.emit(event, body)
        except (ArtifactError, OSError, ValueError) as exc:
            # A file that cannot be kept must not fail the run that wrote it.
            logger.warning("artifact capture skipped for %s: %s", tool_call.name, exc)


__all__ = ["ARTIFACT_CREATED", "ARTIFACT_UPDATED", "ArtifactsAddon", "artifact_frame", "resolve", "site_of"]
