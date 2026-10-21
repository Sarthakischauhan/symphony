// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContextMeter, level, tokens } from "./ContextMeter";
import { ThreadPalette, historyText, search } from "./Palette";
import { initial, reduce } from "./events";
import type { Session } from "./Sidebar";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("formats token counts and thresholds", () => {
  expect(tokens(92200)).toBe("92.2k");
  expect(tokens(128000)).toBe("128k");
  expect(tokens(1048576)).toBe("1m");
  expect(tokens(812)).toBe("812");
  expect(level(0.42)).toBe("low");
  expect(level(0.6)).toBe("warning");
  expect(level(0.85)).toBe("warning");
  expect(level(0.91)).toBe("critical");
});

it("keeps the parent agent's context and usage, ignoring subagents", () => {
  let s = initial();
  s = reduce(s, { type: "event", event: "context", payload: { tokens_used: 500, context_limit: 1000 } }, 1);
  s = reduce(
    s,
    { type: "event", event: "context", payload: { tokens_used: 900, context_limit: 1000, parent_id: "c" } },
    2,
  );
  s = reduce(
    s,
    {
      type: "event",
      event: "usage",
      payload: { prompt_tokens: 10, completion_tokens: 5, reasoning_tokens: 2, cumulative_tokens: 17 },
    },
    3,
  );
  expect(s.context).toEqual({ used: 500, limit: 1000 });
  expect(s.usage).toEqual({ input: 10, output: 5, reasoning: 2 });
});

it("hides the gauge without a limit and shows reasoning only when reported", () => {
  const { container, rerender } = render(<ContextMeter context={{ used: 5, limit: null }} usage={null} />);
  expect(container.textContent).toBe("");
  rerender(<ContextMeter context={{ used: 116480, limit: 128000 }} usage={{ input: 1, reasoning: 8400 }} />);
  const meter = screen.getByLabelText(/^Context 91% full/);
  expect(meter.getAttribute("data-level")).toBe("critical");
  expect(meter.textContent).toContain("Reasoning8.4k");
  expect(meter.textContent).not.toContain("Output");
});

const session = (id: string, first: string): Session => ({
  session_id: id,
  first_message: first,
  updated_at: "2026-10-17T10:00:00Z",
  message_count: 2,
  active: false,
  owned: false,
});

it("searches titles first, then message content with a snippet", () => {
  const sessions = [session("a", "Fix login"), session("b", "Refactor"), session("c", "Docs")];
  const texts = new Map([["b", "we should fix the login redirect"]]);
  const found = search(sessions, texts, "login");
  expect(found.map((m) => m.session.session_id)).toEqual(["a", "b"]);
  expect(found[1].snippet).toContain("login redirect");
  expect(search(sessions, texts, "").length).toBe(3);
  expect(
    historyText({
      events: [],
      children: [],
      messages: [
        { role: "user", content: "hello" },
        { role: "assistant", content: [{ type: "text", text: "world" }] },
        { role: "tool", content: "skip" },
      ],
    }),
  ).toBe("hello\nworld");
});

it("opens with Ctrl+K, filters by content, navigates with arrows and opens on Enter", async () => {
  // jsdom has no layout, so scrolling the highlighted row is a no-op here.
  Element.prototype.scrollIntoView = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => ({
        owned: false,
        model: "",
        events: [],
        children: [],
        messages: [{ role: "user", content: url.includes("/b") ? "flaky pytest hook" : "nothing" }],
      }),
    })),
  );
  const onOpen = vi.fn();
  render(<ThreadPalette sessions={[session("a", "Fix login"), session("b", "Refactor")]} onOpen={onOpen} />);
  await act(async () => {
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  });
  const input = await screen.findByRole("combobox", { name: "Search threads" });
  expect(screen.getAllByRole("option")).toHaveLength(2);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true");
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true");
  fireEvent.change(input, { target: { value: "pytest" } });
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
  expect(screen.getByRole("option").textContent).toContain("flaky pytest hook");
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onOpen).toHaveBeenCalledWith("b");
  await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
});
