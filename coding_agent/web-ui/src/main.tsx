import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChatComposer,
  ChatContextProvider,
  LoadingState,
  MessageContent,
  MessageUsage,
  QuestionWidget,
  ThemeProvider,
  useModel,
  type ChatAdapter,
} from "@sarchauhan/chat";
import "@sarchauhan/chat/styles.css";
import "./style.css";
import { api, withToken } from "./api";
import { historical, initial, reduce, type Row, type State } from "./events";
import { SessionSidebar, type Session } from "./Sidebar";
import { Welcome, type Workspace } from "./Welcome";
import { Button } from "@/components/ui/button";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

type Waiter = { id: string; baseline: number; resolve: () => void };

// Artifact downloads go through the capability-checked session endpoint.
const withDownloads = (session: string, parts: any[]) =>
  parts.map((part) =>
    part.type === "tool" && part.output?.artifact
      ? {
          ...part,
          output: {
            artifact: {
              ...part.output.artifact,
              url: withToken(
                `/api/sessions/${session}/artifacts/${encodeURIComponent(part.output.artifact.id)}`,
              ),
            },
          },
        }
      : part,
  );
function MessageRow({ row, session }: { row: Row; session: string }) {
  if (row.role === "user")
    return (
      <div className="chat-message chat-message-user">
        <div className="chat-message-user-inner">
          <div className="chat-message-bubble">
            <MessageContent parts={row.parts} isUser />
          </div>
        </div>
      </div>
    );
  return (
    <div className="chat-message chat-message-assistant">
      <div className="chat-message-assistant-inner">
        <MessageContent parts={withDownloads(session, row.parts)} />
        <MessageUsage parts={row.parts.filter((p) => p.type === "data")} />
      </div>
    </div>
  );
}
// Show the session's own model in the SDK picker once the registry loads.
function ModelSync({ model }: { model: string }) {
  const { registry, setProvider } = useModel();
  useEffect(() => {
    if (model) setProvider(model.split(":")[0], model);
  }, [model, registry]);
  return null;
}
const knows = (catalog: any, model?: string) =>
  !!model &&
  !!catalog?.providers?.some((p: any) =>
    p.models.some((m: any) => m.id === model),
  );
const activity = (state: State) => {
  const tool = state.rows
    .at(-1)
    ?.parts.findLast(
      (part) => part.type === "tool" && part.state === "input-available",
    );
  return tool ? `Running ${tool.toolName}` : "Thinking";
};

export function App() {
  const [sessions, setSessions] = useState<Session[]>([]),
    [selected, setSelected] = useState(
      sessionStorage.getItem("symphony-session") || "",
    );
  const [state, setState] = useState<State>(initial),
    [owned, setOwned] = useState(false),
    [connected, setConnected] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace | null>(null),
    [catalog, setCatalog] = useState<any>(null);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => localStorage.getItem("symphony-sidebar-open") !== "false",
  );
  const stream = useRef<EventSource | null>(null),
    generation = useRef(0),
    scroller = useRef<HTMLDivElement>(null),
    composer = useRef<HTMLDivElement>(null);
  // Completed runs per session, so a composer send can wait for its own run.
  const runs = useRef<{ done: Record<string, number>; waiters: Waiter[] }>({
    done: {},
    waiters: [],
  });
  const latest = useRef({ selected, owned, sessions, model: state.model });
  latest.current = { selected, owned, sessions, model: state.model };
  const wake = (all = false) => {
    const { done, waiters } = runs.current;
    runs.current.waiters = waiters.filter((w) => {
      const finished = all || (done[w.id] || 0) > w.baseline;
      if (finished) w.resolve();
      return !finished;
    });
  };
  const error = (e: any) =>
    setState((s) => ({ ...s, error: String(e.message || e) }));
  const refresh = () => api("sessions").then(setSessions).catch(error);
  async function open(id: string) {
    const current = ++generation.current;
    stream.current?.close();
    wake(true);
    runs.current.done[id] = 0;
    setConnected(false);
    setOwned(false);
    setSelected(id);
    sessionStorage.setItem("symphony-session", id);
    if (!id) return setState(initial());
    try {
      const data = await api(`sessions/${id}`);
      if (current !== generation.current) return;
      setState({ ...historical(data), model: data.model || "" });
      setOwned(data.owned);
      if (data.owned) {
        let cursor = 0;
        const source = new EventSource(withToken(`/api/sessions/${id}/events`));
        stream.current = source;
        source.onopen = () => setConnected(true);
        source.onerror = () => setConnected(false);
        source.onmessage = (e) => {
          if (current !== generation.current) return;
          const seq = Number(e.lastEventId);
          if (seq <= cursor) return;
          if (seq !== cursor + 1) {
            source.close();
            error(new Error("Event gap; reopen session to recover"));
            return;
          }
          cursor = seq;
          const frame = JSON.parse(e.data);
          setState((s) => reduce(s, frame, seq));
          if (frame.type === "done" || frame.event === "run_started") refresh();
          if (frame.type === "done") {
            runs.current.done[id] = (runs.current.done[id] || 0) + 1;
            wake();
          }
          if (frame.status === "worker_exited") {
            source.close();
            setOwned(false);
            setConnected(false);
            wake(true);
          }
        };
      }
    } catch (e) {
      error(e);
    }
  }
  // Start, resume, or continue the selected session with one prompt. A model
  // picked in the composer restarts an idle worker on that model first.
  async function prompt(text: string, model?: string, effort?: string) {
    const {
      selected: current,
      owned: live,
      sessions: list,
      model: active,
    } = latest.current;
    if (current && !live && list.find((s) => s.session_id === current)?.active)
      throw new Error(
        "This session is open in the TUI. Close it there to continue here.",
      );
    const switching = !!model && live && model !== active;
    const choice = model ? { model } : {};
    let id = current;
    if (!id) id = (await api("sessions", choice)).session_id;
    else if (!live || switching) await api(`sessions/${id}/resume`, choice);
    if (id !== current || !live || switching) await open(id);
    const baseline = runs.current.done[id] || 0;
    await api(`sessions/${id}/prompt`, {
      prompt: text,
      ...(effort ? { reasoning_effort: effort } : {}),
    });
    refresh();
    return { id, baseline };
  }
  const control = useRef({ prompt, error, catalog });
  control.current = { prompt, error, catalog };
  const adapter = useMemo<ChatAdapter>(
    () => ({
      async *sendMessage(input) {
        const { message, signal, model } = input;
        // chat@0.0.1 passes the picked effort; adapter@0.0.1 types omit it.
        const { thinkingLevel } = input as { thinkingLevel?: string };
        if (message.parts.some((part) => part.type === "file")) {
          const failure = new Error("Attachments are not supported yet");
          control.current.error(failure);
          throw failure;
        }
        const text = message.parts
          .map((part: any) => (part.type === "text" ? part.text : ""))
          .join("\n")
          .trim();
        let run: { id: string; baseline: number };
        try {
          // Ignore the SDK's built-in demo registry if the catalog is missing.
          const known = knows(control.current.catalog, model);
          run = await control.current.prompt(
            text,
            known ? model : undefined,
            known ? thinkingLevel : undefined,
          );
        } catch (failure) {
          control.current.error(failure);
          throw failure;
        }
        const finished = new Promise<void>((resolve) =>
          runs.current.waiters.push({ ...run, resolve }),
        );
        wake();
        // The composer's stop button interrupts the Symphony run.
        signal?.addEventListener(
          "abort",
          () => {
            api(`sessions/${run.id}/cancel`, {}).catch(control.current.error);
            wake(true);
          },
          { once: true },
        );
        await finished;
      },
    }),
    [],
  );
  useEffect(() => {
    refresh();
    api("info").then(setWorkspace).catch(error);
    api("models")
      .then(setCatalog)
      .catch(() => setCatalog(null));
    if (selected) void open(selected);
    return () => {
      ++generation.current;
      stream.current?.close();
    };
  }, []);
  useEffect(() => {
    localStorage.setItem("symphony-sidebar-open", String(sidebarOpen));
  }, [sidebarOpen]);
  // chat@0.0.1's composer has no placeholder or label props yet; switch to
  // ChatComposer's placeholder/inputLabel once chat-sdk#33 is released.
  useEffect(() => {
    const input = composer.current?.querySelector("textarea");
    input?.setAttribute("aria-label", "Coding task");
    input?.setAttribute(
      "placeholder",
      selected ? "Describe the next change…" : "Describe a coding task…",
    );
  });
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state, selected]);
  const pending = Object.values(state.pending);
  const session = sessions.find((s) => s.session_id === selected);
  const locked = !!selected && !owned && !!session?.active;
  useEffect(() => {
    document.title = pending.length
      ? "Needs your input · Symphony"
      : state.busy
        ? "Working · Symphony"
        : "Symphony";
  }, [pending.length, state.busy]);
  return (
    <TooltipProvider>
      <SidebarProvider open={sidebarOpen} onOpenChange={setSidebarOpen}>
        <SessionSidebar
          workspace={workspace}
          sessions={sessions}
          selected={selected}
          onCreate={() => void open("")}
          onRefresh={refresh}
          onSelect={(id) => void open(id)}
        />
        <SidebarInset>
          <ThemeProvider defaultTheme="dark">
            <div className="chat-root workspace" data-theme="dark">
              <header className="topbar">
                <SidebarTrigger aria-label="Open session navigation" />
                <div className="topbar-title">
                  <span className="eyebrow" title={workspace?.path}>
                    {workspace
                      ? [workspace.name, workspace.branch]
                          .filter(Boolean)
                          .join(" · ")
                      : "Symphony"}
                  </span>
                  <span className="title" title={selected || undefined}>
                    {session?.first_message ||
                      (selected ? "Untitled session" : "New session")}
                  </span>
                </div>
                {selected && (
                  <span
                    className="status-badge"
                    data-status={
                      owned ? (connected ? "live" : "waiting") : "history"
                    }
                  >
                    {owned
                      ? connected
                        ? "Connected"
                        : "Reconnecting…"
                      : locked
                        ? "Read only"
                        : "History"}
                  </span>
                )}
                {state.model && <span className="model">{state.model}</span>}
                {owned && state.busy && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="pill"
                    onClick={() =>
                      api(`sessions/${selected}/cancel`, {}).catch(error)
                    }
                  >
                    Stop run
                  </Button>
                )}
                {selected && !owned && !locked && (
                  <Button
                    size="sm"
                    className="pill pill-primary"
                    onClick={() =>
                      api(`sessions/${selected}/resume`, {})
                        .then(() => open(selected))
                        .then(refresh)
                        .catch(error)
                    }
                  >
                    Resume session
                  </Button>
                )}
              </header>
              {state.error && (
                <p className="banner" role="alert">
                  {state.error}
                  <button
                    aria-label="Dismiss error"
                    onClick={() => setState((s) => ({ ...s, error: "" }))}
                  >
                    ×
                  </button>
                </p>
              )}
              <div className="chat-messages" ref={scroller} aria-live="polite">
                <div className="chat-messages-inner">
                  {!state.rows.length && (
                    <Welcome
                      workspace={workspace}
                      model={state.model || catalog?.default}
                      resuming={!!selected}
                    />
                  )}
                  {state.rows.map((row) => (
                    <MessageRow key={row.id} row={row} session={selected} />
                  ))}
                  {pending.map((q) => (
                    <QuestionWidget
                      key={q.request_id}
                      prompt={q.question}
                      options={q.choices || []}
                      allowCustom
                      onSubmit={async (answer) => {
                        await api(`sessions/${selected}/answer`, {
                          request_id: q.request_id,
                          value: answer.text || answer.values.join(", "),
                        });
                      }}
                    />
                  ))}
                  {state.busy && !pending.length && (
                    <LoadingState label={activity(state)} compact />
                  )}
                </div>
              </div>
              <div className="chat-composer" ref={composer}>
                {locked && (
                  <p className="composer-note">
                    Open in the TUI. Close it there to continue here.
                  </p>
                )}
                <ChatContextProvider
                  adapter={adapter}
                  defaultThreadId={selected || "new"}
                  defaultProvider=""
                  registryUrl={withToken("/api/models")}
                >
                  <ModelSync model={state.model} />
                  {/* chat@0.0.1 renders its model picker only in the circle
                      variant; style.css keeps the resting composer a bar. */}
                  <ChatComposer
                    showModelSelector={!!catalog}
                    collapsedVariant="circle"
                  />
                </ChatContextProvider>
              </div>
            </div>
          </ThemeProvider>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
