// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { Sidebar, sessionGroups, type Session } from "./Sidebar";
const sessions: Session[] = [
  {
    session_id: "a",
    first_message: "Add streaming retries",
    updated_at: "2026-10-18T10:00:00Z",
    message_count: 12,
    active: false,
    owned: false,
  },
  {
    session_id: "b",
    first_message: "Review security controls",
    updated_at: "2026-10-17T09:00:00Z",
    message_count: 8,
    active: true,
    owned: false,
  },
  {
    session_id: "c",
    first_message: "Fix tool rendering",
    updated_at: "2026-10-01T09:00:00Z",
    message_count: 4,
    active: false,
    owned: false,
  },
];
afterEach(() => {
  cleanup();
  localStorage.clear();
});
it("groups pinned, active, recent and old sessions and searches IDs", () => {
  const groups = sessionGroups(
    sessions,
    ["c"],
    "",
    new Date("2026-10-18T12:00:00Z"),
  );
  expect(groups.map(([name]) => name)).toEqual(["Pinned", "Active", "Today"]);
  expect(sessionGroups(sessions, [], "SECURITY")[0][1][0].session_id).toBe("b");
  expect(sessionGroups(sessions, [], "a")[0][1][0].session_id).toBe("a");
});
it("searches, pins persistently, indicates ownership and navigates with keyboard", () => {
  const select = vi.fn();
  render(
    <Sidebar
      sessions={sessions}
      selected="a"
      open
      onToggle={vi.fn()}
      onSelect={select}
      onCreate={vi.fn()}
      onRefresh={vi.fn()}
    />,
  );
  expect(screen.getByText("Active in TUI · read only")).toBeTruthy();
  const first = screen.getByRole("button", { name: /^Add streaming retries/ });
  expect(first.getAttribute("aria-current")).toBe("page");
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowDown" });
  expect(document.activeElement).not.toBe(first);
  fireEvent.click(
    screen.getByRole("button", { name: "Pin Fix tool rendering" }),
  );
  expect(JSON.parse(localStorage.getItem("symphony-pinned-sessions")!)).toEqual(
    ["c"],
  );
  expect(
    within(screen.getByRole("region", { name: "Pinned" })).getByText(
      "Fix tool rendering",
    ),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Search sessions"), {
    target: { value: "nothing matches" },
  });
  expect(screen.getByText("No matching sessions")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  fireEvent.click(
    screen.getByRole("button", { name: /^Add streaming retries/ }),
  );
  expect(select).toHaveBeenCalledWith("a");
  const splitter = screen.getByRole("separator", { name: "Resize sidebar" });
  fireEvent.keyDown(splitter, { key: "ArrowRight" });
  expect(splitter.getAttribute("aria-valuenow")).toBe("304");
});
it("offers collapse and search shortcuts and mobile escape", () => {
  const toggle = vi.fn();
  render(
    <Sidebar
      sessions={sessions}
      selected=""
      open
      onToggle={toggle}
      onSelect={vi.fn()}
      onCreate={vi.fn()}
      onRefresh={vi.fn()}
    />,
  );
  fireEvent.keyDown(document, { key: "b", ctrlKey: true });
  expect(toggle).toHaveBeenCalledTimes(1);
  Object.defineProperty(window, "innerWidth", {
    value: 390,
    configurable: true,
  });
  fireEvent.keyDown(document, { key: "Escape" });
  expect(toggle).toHaveBeenCalledTimes(2);
  Object.defineProperty(window, "innerWidth", {
    value: 1024,
    configurable: true,
  });
});
