"""Session artifacts: the images, html, csv and json a run produces, stored and versioned."""

from coding_agent.addons.artifacts.addon import ARTIFACT_CREATED, ARTIFACT_UPDATED, ArtifactsAddon
from coding_agent.addons.artifacts.capture import ArtifactError, Snapshot, snapshot_path
from coding_agent.addons.artifacts.kinds import ArtifactKind
from coding_agent.addons.artifacts.store import ArtifactStore, Manifest, Saved

__all__ = [
    "ARTIFACT_CREATED", "ARTIFACT_UPDATED", "ArtifactError", "ArtifactKind", "ArtifactStore",
    "ArtifactsAddon", "Manifest", "Saved", "Snapshot", "snapshot_path",
]
