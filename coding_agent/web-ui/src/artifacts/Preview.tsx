import { useEffect, useState } from "react";
import type { ArtifactManifest } from "../frames";
import { parseCsv } from "./csv";
import { JsonTree } from "./JsonTree";

// Larger tables are cut; the full file stays one click away.
const MAX_ROWS = 500;

function useText(url: string) {
  const [text, setText] = useState<string | null>(null),
    [failure, setFailure] = useState("");
  useEffect(() => {
    let live = true;
    setText(null);
    setFailure("");
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.statusText))))
      .then((body) => live && setText(body))
      .catch((e: unknown) => live && setFailure(String(e)));
    return () => {
      live = false;
    };
  }, [url]);
  return { text, failure };
}

function CsvTable({ url }: { url: string }) {
  const { text, failure } = useText(url);
  if (failure) return <p className="artifact-error">{failure}</p>;
  if (text === null) return <p className="artifact-empty">Loading…</p>;
  const [head = [], ...body] = parseCsv(text, MAX_ROWS + 1);
  return (
    <div className="csv-scroll">
      <table className="csv-table">
        <thead>
          <tr>
            {head.map((cell, i) => (
              <th key={i}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, MAX_ROWS).map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <td key={i}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length > MAX_ROWS && (
        <p className="artifact-empty">First {MAX_ROWS} rows shown.</p>
      )}
    </div>
  );
}

function JsonView({ url }: { url: string }) {
  const { text, failure } = useText(url);
  if (failure) return <p className="artifact-error">{failure}</p>;
  if (text === null) return <p className="artifact-empty">Loading…</p>;
  return <JsonTree text={text} />;
}

function ImageViewer({ url, title }: { url: string; title: string }) {
  const [actual, setActual] = useState(false);
  return (
    <button
      type="button"
      className="image-viewer"
      data-actual={actual}
      aria-label={actual ? "Fit image" : "Show actual size"}
      onClick={() => setActual(!actual)}
    >
      <img src={url} alt={title} />
    </button>
  );
}

/** The latest version of one artifact, by kind. */
export function ArtifactPreview({
  artifact,
  base,
}: {
  artifact: ArtifactManifest;
  base: string;
}) {
  const url = `${base}/${artifact.id}/${artifact.entry}`;
  switch (artifact.kind) {
    case "html":
      // Scripts run, but without allow-same-origin the page is an opaque
      // origin: no app cookies, storage or API. The server's CSP sandboxes it too.
      return (
        <iframe
          className="html-frame"
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          src={url}
          title={artifact.title}
        />
      );
    case "csv":
      return <CsvTable url={url} />;
    case "json":
      return <JsonView url={url} />;
    case "image":
      return <ImageViewer url={url} title={artifact.title} />;
  }
}
