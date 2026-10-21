"""Keep a file or website folder as a session artifact."""

from __future__ import annotations

from pydantic import Field

from coding_agent.addons.artifacts import ArtifactKind, snapshot_path
from coding_agent.tools.base import NonEmptyPath, ToolArgsModel, WorkspaceTool


class SaveArtifactArgs(ToolArgsModel):
    path: NonEmptyPath = Field(
        ...,
        description=(
            "File to keep, or for kind html a folder whose entry is index.html. "
            "Relative paths start at the working directory."
        ),
    )
    kind: ArtifactKind = Field(..., description="html, csv, json or image.")
    title: str = Field("", description="Short name shown for the artifact; defaults to the file name.")


class SaveArtifactTool(WorkspaceTool):
    """Validates the path for its kind; the artifacts add-on stores it after the call."""

    name = "save_artifact"
    description = (
        "Save a file as a session artifact the user can open and preview. html, csv, json and "
        "image files you write are saved automatically; use this for other paths, such as a "
        "file a command produced or a website folder with index.html."
    )
    args_model = SaveArtifactArgs

    def run(self, path: str, kind: ArtifactKind, title: str = "") -> str:
        try:
            captured = snapshot_path(self.resolve_path(path), self.workspace, ArtifactKind(kind), title)
        except (ValueError, OSError, TypeError) as exc:
            return f"error: cannot save {path} as a {kind} artifact: {exc}"
        return f"saved {captured.source} as {captured.kind.value} artifact {captured.title!r}"
