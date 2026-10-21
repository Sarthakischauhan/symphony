// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { parseCsv } from "./csv";
import { JsonTree } from "./JsonTree";
import { ArtifactPreview } from "./Preview";
import { ArtifactsPanel } from "./Panel";
import {
  parseFrame,
  type ArtifactKind,
  type ArtifactManifest,
} from "../frames";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const BASE = "/artifacts/cap/s1";
const manifest = (
  kind: ArtifactKind,
  id: string,
  entry: string,
): ArtifactManifest => ({
  id,
  kind,
  title: entry.split("/").at(-1) ?? entry,
  created_at: "2026-10-21T21:00:00Z",
  updated_at: "2026-10-21T21:00:00Z",
  version: 1,
  tool_call_id: "c1",
  source: entry,
  entry,
  mime: "text/plain",
  sha256: "0".repeat(64),
  size: 10,
});
const respond = (routes: Record<string, string>) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = Object.entries(routes).find(([path]) =>
        url.startsWith(path),
      )?.[1];
      return body === undefined
        ? new Response("{}", { status: 404 })
        : new Response(body, { status: 200 });
    }),
  );

it("parses quoted csv fields", () => {
  expect(parseCsv('a,b\n"x, y","say ""hi"""\r\n"multi\nline",2')).toEqual([
    ["a", "b"],
    ["x, y", 'say "hi"'],
    ["multi\nline", "2"],
  ]);
  expect(parseCsv("a\n1\n2\n3\n", 2)).toEqual([["a"], ["1"]]);
  expect(parseCsv("")).toEqual([]);
});

it("collapses and expands json", () => {
  render(
    <JsonTree text='{"user": {"name": "Ada", "tags": ["x"]}, "n": 3, "none": null}' />,
  );
  expect(screen.getByText('"Ada"')).toBeTruthy();
  expect(screen.getByText("3")).toBeTruthy();
  const tags = screen.getByRole("button", { name: /tags/ });
  expect(tags.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(tags);
  expect(screen.getByText('"x"')).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /user/ }));
  expect(screen.queryByText('"Ada"')).toBeNull();
});

it("reports invalid json", () => {
  render(<JsonTree text="{nope" />);
  expect(screen.getByText(/Invalid JSON/)).toBeTruthy();
});

it("sandboxes html without same-origin", () => {
  const { container } = render(
    <ArtifactPreview
      artifact={manifest("html", "a1", "v1/index.html")}
      base={BASE}
    />,
  );
  const frame = container.querySelector("iframe");
  expect(frame?.getAttribute("sandbox")).toBe("allow-scripts");
  expect(frame?.getAttribute("src")).toBe(`${BASE}/a1/v1/index.html`);
});

it("shows csv as a table and images in a viewer", async () => {
  respond({ [`${BASE}/c1/`]: "city,temp\nOslo,4\nLima,19\n" });
  render(
    <ArtifactPreview
      artifact={manifest("csv", "c1", "v1/t.csv")}
      base={BASE}
    />,
  );
  expect(
    await screen.findByRole("columnheader", { name: "city" }),
  ).toBeTruthy();
  expect(screen.getAllByRole("row")).toHaveLength(3);
  cleanup();
  render(
    <ArtifactPreview
      artifact={manifest("image", "i1", "v1/chart.png")}
      base={BASE}
    />,
  );
  const img = screen.getByRole("img", { name: "chart.png" });
  expect(img.getAttribute("src")).toBe(`${BASE}/i1/v1/chart.png`);
  fireEvent.click(screen.getByRole("button", { name: "Show actual size" }));
  expect(screen.getByRole("button", { name: "Fit image" })).toBeTruthy();
});

it("lists the session's artifacts and previews the picked one", async () => {
  const listing = {
    base: BASE,
    artifacts: [
      manifest("json", "j1", "v1/data.json"),
      manifest("html", "h1", "v1/index.html"),
    ],
  };
  respond({
    "/api/sessions/s1/artifacts": JSON.stringify(listing),
    [`${BASE}/j1/`]: '{"ok": true}',
  });
  const { container } = render(
    <ArtifactsPanel sessionId="s1" revision={0} onClose={() => {}} />,
  );
  // The newest is shown first.
  await waitFor(() => expect(container.querySelector("iframe")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /data\.json/ }));
  expect(await screen.findByText("true")).toBeTruthy();
});

it("accepts artifact events", () => {
  const payload = {
    ...manifest("csv", "c1", "v1/t.csv"),
    path: "/home/u/.symphony/x",
  };
  expect(
    parseFrame({ type: "event", event: "artifact/created", payload }),
  ).not.toBeNull();
  expect(
    parseFrame({ type: "event", event: "artifact/updated", payload }),
  ).not.toBeNull();
});
