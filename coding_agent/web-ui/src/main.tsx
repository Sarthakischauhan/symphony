import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  ChatComposer,
  ChatContextProvider,
  LoadingState,
  MessageContent,
  MessageUsage,
  ProviderLogo,
  QuestionWidget,
  ThemeProvider,
  useModel,
  type ChatAdapter,
} from "@sarchauhan/chat";
import "@sarchauhan/chat/styles.css";
import "./style.css";
import { api, withToken } from "./api";
import { ApprovalCard } from "./Approval";
import { historical, initial, reduce, type Row, type State } from "./events";
import {
  parseFrame,
  type Frame,
  type SessionHistory,
  type SessionSummary,
  type Workspace,
} from "./frames";
import { isDataPart, isToolPart } from "@sarchauhan/protocol";
import { SessionSidebar, stored, type Session } from "./Sidebar";
import type { Preferences } from "./Settings";
import { Welcome } from "./Welcome";
import { ContextMeter } from "./ContextMeter";
import { ThreadPalette } from "./Palette";
import { Folder, GitBranch } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

type Waiter = { id: string; baseline: number; resolve: () => void };

type SessionView = SessionHistory & { owned: boolean; model: string };
type CatalogModel = {
  id: string;
  label: string;
  thinkingLevels?: string[];
};
type Catalog = {
  defaultProviderId: string;
  default: string;
  providers: {
    id: string;
    label: string;
    defaultModel: string;
    models: CatalogModel[];
  }[];
};
// Memoized: reduce() keeps unchanged rows by identity, so a streamed token
// re-renders only the row it lands in.
const MessageRow = memo(function MessageRow({
  row,
  showUsage,
}: {
  row: Row;
  showUsage: boolean;
}) {
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
        <MessageContent parts={row.parts} />
        {showUsage && <MessageUsage parts={row.parts.filter(isDataPart)} />}
      </div>
    </div>
  );
});
// The catalog provider whose model rows include `model` (the row's
// provider is the API route, not the id's prefix).
const providerOf = (catalog: Catalog | null, model: string) =>
  catalog?.providers.find((p) => p.models.some((m) => m.id === model));
// Show the session's own model in the SDK picker once the registry loads.
function ModelSync({ model, catalog }: { model: string; catalog: Catalog | null }) {
  const { registry, setProvider } = useModel();
  useEffect(() => {
    const provider = providerOf(catalog, model);
    if (provider) setProvider(provider.id, model);
  }, [model, catalog, registry]);
  return null;
}
// The header's model: its provider and catalog label; an unlisted model shows its id.
function modelParts(catalog: Catalog | null, model: string) {
  const provider = providerOf(catalog, model);
  const row = provider?.models.find((m) => m.id === model);
  return { provider: provider?.id ?? "", name: row ? row.label : model };
}
// The host stages PNG, JPEG, GIF and WebP images for the stdio run frame; the
// composer filters picked, pasted and dropped files to these.
const IMAGE_TYPES = "image/png,image/jpeg,image/gif,image/webp";
// A composer file part as the web host's prompt attachment (a data URL).
type Attachment = { filename: string; media_type: string; data_url: string };
const knows = (catalog: Catalog | null, model?: string) =>
  !!model &&
  !!catalog?.providers.some((p) => p.models.some((m) => m.id === model));
const activity = (state: State) => {
  const tool = state.rows
    .at(-1)
    ?.parts.filter(isToolPart)
    .findLast((part) => part.state === "input-available");
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
    [catalog, setCatalog] = useState<Catalog | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => localStorage.getItem("symphony-sidebar-open") !== "false",
  );
  const [preferences, setPreferences] = useState<Preferences>(() => ({
    showUsage: true,
    ...stored("symphony-preferences", {}),
  }));
  const stream = useRef<EventSource | null>(null),
    generation = useRef(0),
    scroller = useRef<HTMLDivElement>(null),
    // Follow new output only while the reader is at the bottom.
    following = useRef(true),
    backlog = useRef<{ frame: Frame; seq: number }[]>([]);
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
  const error = (e: unknown) =>
    setState((s) => ({
      ...s,
      error: e instanceof Error ? e.message : String(e),
    }));
  // Frames that arrive between paints apply together in one render.
  const enqueue = (frame: Frame, seq: number) => {
    if (backlog.current.push({ frame, seq }) > 1) return;
    const flush = () => {
      const frames = backlog.current;
      backlog.current = [];
      setState((s) =>
        frames.reduce((acc, item) => reduce(acc, item.frame, item.seq), s),
      );
    };
    // Hidden tabs get no animation frames; keep the title badge current.
    if (document.hidden) setTimeout(flush, 100);
    else requestAnimationFrame(flush);
  };
  const refresh = () =>
    api<(SessionSummary & { owned: boolean })[]>("sessions")
      .then(setSessions)
      .catch(error);
  async function open(id: string) {
    const current = ++generation.current;
    stream.current?.close();
    backlog.current = [];
    following.current = true;
    wake(true);
    runs.current.done[id] = 0;
    setConnected(false);
    setOwned(false);
    setSelected(id);
    sessionStorage.setItem("symphony-session", id);
    if (!id) return setState(initial());
    try {
      const data = await api<SessionView>(`sessions/${id}`);
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
          const frame = parseFrame(JSON.parse(e.data));
          if (!frame) return;
          enqueue(frame, seq);
          if (
            frame.type === "done" ||
            (frame.type === "event" && frame.event === "run_started")
          )
            refresh();
          if (frame.type === "done") {
            runs.current.done[id] = (runs.current.done[id] || 0) + 1;
            wake();
          }
          if (frame.type === "done" && frame.status === "worker_exited") {
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
  // picked in the composer switches the live worker through the protocol.
  async function prompt(
    text: string,
    model?: string,
    effort?: string,
    attachments: Attachment[] = [],
  ) {
    const {
      selected: current,
      owned: live,
      sessions: list,
      model: active,
    } = latest.current;
    if (current && !live && list.find((s) => s.session_id === current)?.active)
      throw new Error(
        "This session is open in another Symphony process. Close it there to continue here.",
      );
    // Sending a prompt returns the transcript to the newest output.
    following.current = true;
    const switching = !!model && live && model !== active;
    const choice = model ? { model } : {};
    type Opened = { session_id: string; model: string };
    let id = current;
    if (!id) id = (await api<Opened>("sessions", choice)).session_id;
    else if (!live || switching) {
      const opened = await api<Opened>(`sessions/${id}/resume`, choice);
      if (live) setState((s) => ({ ...s, model: opened.model }));
    }
    if (id !== current || !live) await open(id);
    const baseline = runs.current.done[id] || 0;
    await api(`sessions/${id}/prompt`, {
      prompt: text,
      ...(effort ? { reasoning_effort: effort } : {}),
      // The host stages each image and passes its path on the stdio run frame.
      ...(attachments.length ? { attachments } : {}),
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
        const attachments = message.parts.flatMap((part): Attachment[] => {
          if (part.type !== "file" || !("mediaType" in part)) return [];
          const { mediaType, url, filename } = part;
          if (typeof mediaType !== "string") return [];
          if (!mediaType.startsWith("image/") || typeof url !== "string") return [];
          return [
            {
              filename: typeof filename === "string" && filename ? filename : "image",
              media_type: mediaType,
              data_url: url,
            },
          ];
        });
        const text = message.parts
          .map((part) => (part.type === "text" ? part.text : ""))
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
            attachments,
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
    api<Workspace>("info").then(setWorkspace).catch(error);
    api<Catalog>("models")
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
  useEffect(() => {
    localStorage.setItem("symphony-preferences", JSON.stringify(preferences));
  }, [preferences]);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [state, selected]);
  const pending = Object.values(state.pending);
  const session = sessions.find((s) => s.session_id === selected);
  const locked = !!selected && !owned && !!session?.active;
  const shown = modelParts(catalog, state.model);
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
          defaultModel={catalog?.default}
          preferences={preferences}
          onPreferencesChange={setPreferences}
          sessions={sessions}
          selected={selected}
          onCreate={() => void open("")}
          onRefresh={refresh}
          onSelect={(id) => void open(id)}
        />
        <ThreadPalette sessions={sessions} onOpen={(id) => void open(id)} />
        <SidebarInset>
          <ThemeProvider defaultTheme="dark">
            <div className="chat-root workspace" data-theme="dark">
              <header className="topbar">
                <SidebarTrigger aria-label="Open session navigation" />
                <div className="topbar-title">
                  <span className="topbar-place" title={workspace?.path}>
                    {workspace ? (
                      <>
                        <span>
                          <Folder aria-hidden="true" />
                          {workspace.name}
                        </span>
                        {workspace.branch && (
                          <span>
                            <GitBranch aria-hidden="true" />
                            {workspace.branch}
                          </span>
                        )}
                      </>
                    ) : (
                      "symphony"
                    )}
                  </span>
                  <span className="title" title={selected || undefined}>
                    {session?.first_message ||
                      (selected ? "Untitled session" : "New session")}
                  </span>
                </div>
                {/* A live, connected session shows its context gauge; other
                    states keep a short mono status. */}
                {selected && !(owned && connected) && (
                  <span
                    className="status-badge"
                    data-status={owned ? "waiting" : "history"}
                  >
                    {owned ? "reconnecting…" : locked ? "read only" : "history"}
                  </span>
                )}
                <ContextMeter context={state.context} usage={state.usage} />
                {state.model && (
                  <span className="model" title={state.model}>
                    {shown.provider && <ProviderLogo provider={shown.provider} />}
                    {shown.name}
                  </span>
                )}
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
              <div
                className="chat-messages"
                ref={scroller}
                aria-live="polite"
                onScroll={(e) => {
                  const el = e.currentTarget;
                  following.current =
                    el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                }}
              >
                <div className="chat-messages-inner">
                  {!state.rows.length && (
                    <Welcome />
                  )}
                  {state.rows.map((row) => (
                    <MessageRow
                      key={row.id}
                      row={row}
                      showUsage={preferences.showUsage}
                    />
                  ))}
                  {pending.map((q) => {
                    // Both widgets answer through the stdio answer frame.
                    const answer = async (value: string) => {
                      await api(`sessions/${selected}/answer`, {
                        request_id: q.request_id,
                        value,
                      });
                      // The protocol has no answered frame; the next run
                      // event (or done) confirms it.
                      setState((s) => {
                        const pending = { ...s.pending };
                        delete pending[q.request_id];
                        return { ...s, pending };
                      });
                    };
                    return q.kind === "approval" ? (
                      <ApprovalCard
                        key={q.request_id}
                        question={q}
                        onAnswer={answer}
                      />
                    ) : (
                      <QuestionWidget
                        key={q.request_id}
                        prompt={q.question}
                        options={q.choices || []}
                        allowCustom
                        onSubmit={(reply) =>
                          answer(reply.text || reply.values.join(", "))
                        }
                      />
                    );
                  })}
                  {state.busy && !pending.length && (
                    <LoadingState label={activity(state)} compact />
                  )}
                </div>
              </div>
              <div className="chat-composer">
                {locked && (
                  <p className="composer-note">
                    Open in another Symphony process. Close it there to continue
                    here.
                  </p>
                )}
                <ChatContextProvider
                  adapter={adapter}
                  defaultThreadId={selected || "new"}
                  defaultProvider=""
                  registryUrl={withToken("/api/models")}
                >
                  <ModelSync model={state.model} catalog={catalog} />
                  {/* The circle variant carries the model picker; style.css
                      keeps the resting composer a full-width bar. */}
                  <ChatComposer
                    showModelSelector={!!catalog}
                    collapsedVariant="circle"
                    attachmentAccept={IMAGE_TYPES}
                    inputLabel="Coding task"
                    placeholder={
                      selected
                        ? "Describe the next change…"
                        : "Describe a coding task…"
                    }
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
