import { useState } from "react";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const isBranch = (value: Json): value is Json[] | { [key: string]: Json } =>
  value !== null && typeof value === "object";

function Leaf({ value }: { value: Json }) {
  const kind = value === null ? "null" : typeof value;
  return (
    <span className={`json-${kind}`}>
      {typeof value === "string" ? JSON.stringify(value) : String(value)}
    </span>
  );
}

// One key: objects and arrays open and close; the first two levels start open.
function JsonNode({
  name,
  value,
  depth,
}: {
  name: string | null;
  value: Json;
  depth: number;
}) {
  const [open, setOpen] = useState(depth < 2);
  const label = name !== null && <span className="json-key">{name}: </span>;
  if (!isBranch(value))
    return (
      <div className="json-row">
        {label}
        <Leaf value={value} />
      </div>
    );
  const entries: [string, Json][] = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
  const [start, end] = Array.isArray(value) ? ["[", "]"] : ["{", "}"];
  return (
    <div className="json-row">
      <button
        type="button"
        className="json-toggle"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "▾" : "▸"} {label}
        {start}
        {!open && (
          <span className="json-count">
            {entries.length} {Array.isArray(value) ? "items" : "keys"}
            {end}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="json-children">
            {entries.map(([key, item]) => (
              <JsonNode key={key} name={key} value={item} depth={depth + 1} />
            ))}
          </div>
          <span>{end}</span>
        </>
      )}
    </div>
  );
}

export function JsonTree({ text }: { text: string }) {
  let value: Json;
  try {
    value = JSON.parse(text);
  } catch (e) {
    return <p className="artifact-error">Invalid JSON: {String(e)}</p>;
  }
  return (
    <div className="json-tree">
      <JsonNode name={null} value={value} depth={0} />
    </div>
  );
}
