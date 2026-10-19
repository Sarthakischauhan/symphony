import { useEffect, useState } from "react";
import { Folder, GitBranch, Plus, RefreshCw, Search, Star } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import logo from "./assets/symphony-logo.svg";
import type { Workspace } from "./Welcome";

export type Session = {
  session_id: string;
  first_message: string;
  updated_at: string;
  message_count: number;
  active: boolean;
  owned: boolean;
};
type Props = {
  workspace?: Workspace | null;
  sessions: Session[];
  selected: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRefresh: () => void;
};
function stored<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}
export function sessionGroups(
  sessions: Session[],
  pins: string[],
  query: string,
  now = new Date(),
) {
  const day = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const groups = new Map<string, Session[]>([
    ["Pinned", []],
    ["Active", []],
    ["Today", []],
    ["Previous 7 days", []],
    ["Older", []],
  ]);
  for (const session of [...sessions].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  )) {
    if (
      !`${session.first_message} ${session.session_id}`
        .toLowerCase()
        .includes(query.toLowerCase().trim())
    )
      continue;
    const time = Date.parse(session.updated_at);
    const group = pins.includes(session.session_id)
      ? "Pinned"
      : session.active
        ? "Active"
        : time >= day
          ? "Today"
          : time >= day - 7 * 86400000
            ? "Previous 7 days"
            : "Older";
    groups.get(group)!.push(session);
  }
  return [...groups].filter(([, items]) => items.length);
}
function meta(session: Session) {
  if (session.active)
    return session.owned
      ? "Active in Web"
      : "Active in another process · read only";
  const date = new Date(session.updated_at);
  const day = Number.isNaN(date.getTime())
    ? "Saved"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${day} · ${session.message_count} ${session.message_count === 1 ? "message" : "messages"}`;
}
export function SessionSidebar({
  workspace,
  sessions,
  selected,
  onSelect,
  onCreate,
  onRefresh,
}: Props) {
  const { isMobile, setOpenMobile } = useSidebar();
  const [query, setQuery] = useState("");
  const [pins, setPins] = useState<string[]>(() =>
    stored("symphony-pinned-sessions", []),
  );
  useEffect(() => {
    localStorage.setItem("symphony-pinned-sessions", JSON.stringify(pins));
  }, [pins]);
  const groups = sessionGroups(sessions, pins, query);
  const pin = (id: string) =>
    setPins((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );
  const close = () => isMobile && setOpenMobile(false);
  return (
    <Sidebar aria-label="Session navigation">
      <SidebarHeader>
        <div className="brand">
          <img className="brand-logo" src={logo} alt="Symphony" />
          <Button
            variant="ghost"
            size="icon"
            className="ml-auto size-7"
            onClick={onRefresh}
            aria-label="Refresh sessions"
            title="Refresh sessions"
          >
            <RefreshCw />
          </Button>
        </div>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              className="new-session"
              onClick={() => {
                onCreate();
                close();
              }}
            >
              <Plus />
              <span>New session</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <label className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 opacity-50" />
          <SidebarInput
            className="pl-8"
            aria-label="Search sessions"
            placeholder="Search sessions"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </SidebarHeader>
      <SidebarContent>
        {!groups.length && (
          <div className="sidebar-empty">
            <strong>
              {query ? "No matching sessions" : "No sessions yet"}
            </strong>
            <p>
              {query
                ? "Try another title or session ID."
                : "Start a session to work with your code."}
            </p>
            {query && (
              <button className="pill" onClick={() => setQuery("")}>
                Clear search
              </button>
            )}
          </div>
        )}
        {groups.map(([name, items]) => (
          <SidebarGroup key={name} role="region" aria-label={name}>
            <SidebarGroupLabel>{name}</SidebarGroupLabel>
            <SidebarMenu>
              {items.map((session) => {
                const pinned = pins.includes(session.session_id);
                const title = session.first_message || "Untitled session";
                return (
                  <SidebarMenuItem key={session.session_id}>
                    <SidebarMenuButton
                      size="lg"
                      isActive={session.session_id === selected}
                      aria-current={
                        session.session_id === selected ? "page" : undefined
                      }
                      title={title}
                      onClick={() => {
                        onSelect(session.session_id);
                        close();
                      }}
                    >
                      <span
                        className="session-status"
                        data-status={
                          session.active
                            ? session.owned
                              ? "web"
                              : "locked"
                            : undefined
                        }
                        aria-hidden="true"
                      />
                      <span className="session-copy">
                        <span className="session-title">{title}</span>
                        <span className="session-meta">{meta(session)}</span>
                      </span>
                    </SidebarMenuButton>
                    <SidebarMenuAction
                      showOnHover={!pinned}
                      data-pinned={pinned || undefined}
                      aria-label={`${pinned ? "Unpin" : "Pin"} ${title}`}
                      aria-pressed={pinned}
                      title={pinned ? "Unpin session" : "Pin session"}
                      onClick={() => pin(session.session_id)}
                    >
                      <Star />
                    </SidebarMenuAction>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        {workspace && (
          <div className="sidebar-workspace" title={workspace.path}>
            <span>
              <Folder aria-hidden="true" />
              {workspace.display}
            </span>
            {workspace.branch && (
              <span>
                <GitBranch aria-hidden="true" />
                {workspace.branch}
              </span>
            )}
          </div>
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
