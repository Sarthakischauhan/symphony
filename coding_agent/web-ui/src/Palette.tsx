import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api } from "./api";
import type { SessionHistory } from "./frames";
import type { Session } from "./Sidebar";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

// Threads to load content for: the most recent ones, each over session/history.
const CONTENT_LIMIT = 50;

/** Plain text of a session's user and assistant messages, for content search. */
export function historyText(history: SessionHistory) {
  return history.messages
    .flatMap((message) => {
      if (message.role !== "user" && message.role !== "assistant") return [];
      if (typeof message.content === "string") return [message.content];
      return (message.content || []).flatMap((part) =>
        typeof part.text === "string" ? [part.text] : [],
      );
    })
    .join("\n");
}
export type Match = { session: Session; snippet?: string };
/** Title matches first, then content matches with the text around the hit. */
export function search(sessions: Session[], texts: Map<string, string>, query: string): Match[] {
  const q = query.trim().toLowerCase();
  if (!q) return sessions.map((session) => ({ session }));
  const byTitle: Match[] = [],
    byContent: Match[] = [];
  for (const session of sessions) {
    if (session.first_message.toLowerCase().includes(q)) {
      byTitle.push({ session });
      continue;
    }
    const text = texts.get(session.session_id) ?? "";
    const at = text.toLowerCase().indexOf(q);
    if (at < 0) continue;
    const start = Math.max(0, at - 40);
    const snippet = text.slice(start, at + q.length + 60).replace(/\s+/g, " ").trim();
    byContent.push({ session, snippet: `${start > 0 ? "…" : ""}${snippet}…` });
  }
  return [...byTitle, ...byContent];
}

/** Cmd+K / Ctrl+K: find a thread by title or content. */
export function ThreadPalette({
  sessions,
  onOpen,
}: {
  sessions: Session[];
  onOpen: (id: string) => void;
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(""),
    [active, setActive] = useState(0);
  const [texts, setTexts] = useState(() => new Map<string, string>());
  const loaded = useRef(new Map<string, string>());
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    let cancelled = false;
    // Content comes from session/history; a thread is reloaded when it changed.
    const stale = sessions
      .slice(0, CONTENT_LIMIT)
      .filter((s) => loaded.current.get(s.session_id) !== s.updated_at);
    void Promise.all(
      stale.map((s) =>
        api<SessionHistory>(`sessions/${s.session_id}`)
          .then((history) => [s, historyText(history)] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      setTexts((current) => {
        const next = new Map(current);
        for (const result of results) {
          if (!result) continue;
          next.set(result[0].session_id, result[1]);
          loaded.current.set(result[0].session_id, result[0].updated_at);
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [open]);
  const matches = useMemo(() => search(sessions, texts, query), [sessions, texts, query]);
  const choose = (match: Match | undefined) => {
    if (!match) return;
    setOpen(false);
    onOpen(match.session.session_id);
  };
  const move = (step: number) => {
    if (!matches.length) return;
    const next = (active + step + matches.length) % matches.length;
    setActive(next);
    list.current?.children[next]?.scrollIntoView({ block: "nearest" });
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="palette top-[18%] translate-y-0 gap-0 p-0 sm:max-w-xl" showCloseButton={false} aria-describedby={undefined}>
        <DialogTitle className="sr-only">Search threads</DialogTitle>
        <label className="palette-search">
          <Search aria-hidden="true" />
          <input
            autoFocus
            placeholder="Search threads…"
            aria-label="Search threads"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={matches[active] ? `palette-${active}` : undefined}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") move(1);
              else if (event.key === "ArrowUp") move(-1);
              else if (event.key === "Enter") choose(matches[active]);
              else return;
              event.preventDefault();
            }}
          />
          <kbd>esc</kbd>
        </label>
        <ul className="palette-results" id="palette-results" role="listbox" ref={list}>
          {matches.length === 0 && <li className="palette-empty">no matching threads</li>}
          {matches.map((match, index) => (
            <li
              key={match.session.session_id}
              id={`palette-${index}`}
              role="option"
              aria-selected={index === active}
              data-active={index === active || undefined}
              onMouseMove={() => setActive(index)}
              onClick={() => choose(match)}
            >
              <span className="palette-title">
                {match.session.first_message || "Untitled session"}
              </span>
              <span className="palette-meta">
                {match.snippet ??
                  `${new Date(match.session.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }).toLowerCase()} · ${match.session.message_count} messages`}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
