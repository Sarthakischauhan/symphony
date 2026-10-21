import { useEffect, useState } from "react";
import { Braces, FileImage, Globe, Table, X } from "lucide-react";
import { api } from "../api";
import type { ArtifactKind, ArtifactListing } from "../frames";
import { ArtifactPreview } from "./Preview";

const ICONS: Record<ArtifactKind, typeof Globe> = {
  html: Globe,
  csv: Table,
  json: Braces,
  image: FileImage,
};

/**
 * The session's artifacts and a preview of the picked one. `revision` changes
 * with every artifact event, so new versions show up while a run goes on.
 */
export function ArtifactsPanel({
  sessionId,
  revision,
  onClose,
}: {
  sessionId: string;
  revision: number;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<ArtifactListing | null>(null),
    [picked, setPicked] = useState(""),
    [failure, setFailure] = useState("");
  useEffect(() => {
    let live = true;
    api<ArtifactListing>(`sessions/${sessionId}/artifacts`)
      .then((value) => {
        if (!live) return;
        setListing(value);
        setFailure("");
      })
      .catch((e: unknown) => live && setFailure(String(e)));
    return () => {
      live = false;
    };
  }, [sessionId, revision]);
  const artifacts = listing?.artifacts ?? [];
  const shown = artifacts.find((a) => a.id === picked) ?? artifacts.at(-1);
  return (
    <aside className="artifacts-panel" aria-label="Artifacts">
      <header className="artifacts-head">
        <span>Artifacts</span>
        <button type="button" aria-label="Close artifacts" onClick={onClose}>
          <X aria-hidden="true" />
        </button>
      </header>
      {failure && <p className="artifact-error">{failure}</p>}
      {listing && !artifacts.length && (
        <p className="artifact-empty">
          No artifacts yet. HTML, CSV, JSON and image files the agent writes
          show up here.
        </p>
      )}
      {!!artifacts.length && (
        <ul className="artifacts-list">
          {artifacts.map((artifact) => {
            const Icon = ICONS[artifact.kind];
            return (
              <li key={artifact.id}>
                <button
                  type="button"
                  aria-current={artifact.id === shown?.id}
                  onClick={() => setPicked(artifact.id)}
                  title={artifact.source}
                >
                  <Icon aria-hidden="true" />
                  <span className="artifact-title">{artifact.title}</span>
                  <span className="artifact-meta">
                    {artifact.kind} · v{artifact.version}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {shown && listing && (
        <section
          className="artifact-preview"
          aria-label={`Preview of ${shown.title}`}
        >
          <a
            className="artifact-open"
            href={`${listing.base}/${shown.id}/${shown.entry}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open {shown.entry.split("/").at(-1)} ↗
          </a>
          <ArtifactPreview
            key={`${shown.id}:${shown.version}`}
            artifact={shown}
            base={listing.base}
          />
        </section>
      )}
    </aside>
  );
}
