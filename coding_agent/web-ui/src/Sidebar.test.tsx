// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { SessionSidebar, sessionGroups, type Session } from "./Sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
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
const mount = (props: Partial<Parameters<typeof SessionSidebar>[0]> = {}) =>
  render(
    <TooltipProvider>
      <SidebarProvider>
        <SessionSidebar
          sessions={sessions}
          selected="a"
          onSelect={vi.fn()}
          onCreate={vi.fn()}
          onRefresh={vi.fn()}
          {...props}
        />
      </SidebarProvider>
    </TooltipProvider>,
  );
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
it("searches, pins persistently, indicates ownership and selects", () => {
  const select = vi.fn(),
    create = vi.fn(),
    refresh = vi.fn();
  mount({ onSelect: select, onCreate: create, onRefresh: refresh });
  expect(screen.getByText("Active in TUI · read only")).toBeTruthy();
  const first = screen.getByRole("button", { name: /^Add streaming retries/ });
  expect(first.getAttribute("aria-current")).toBe("page");
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
  fireEvent.click(screen.getByRole("button", { name: "New session" }));
  expect(create).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh sessions" }));
  expect(refresh).toHaveBeenCalled();
});
it("collapses with the shadcn keyboard shortcut", () => {
  const { container } = mount();
  const state = () =>
    container.querySelector("[data-state]")?.getAttribute("data-state");
  expect(state()).toBe("expanded");
  fireEvent.keyDown(window, { key: "b", ctrlKey: true });
  expect(state()).toBe("collapsed");
});
