/**
 * Application shell: fixed sidebar, topbar, routed content.
 *
 * The sidebar carries live corpus state (documents and chunks indexed) because in a RAG tool
 * "what is actually searchable right now" is the single most important piece of context, and
 * an answer that looks wrong is usually a corpus problem rather than a model problem.
 */

import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  FileText,
  FlaskConical,
  LayoutDashboard,
  MessagesSquare,
  Moon,
  Settings as SettingsIcon,
  Sun,
} from "lucide-react";
import { api } from "../lib/api";
import { POLL_INTERVAL_MS, queryKeys } from "../lib/queryKeys";
import { cn, formatCount } from "../lib/format";
import { Badge } from "../components/ui";
import { useTheme } from "./useTheme";

const navigation = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/chat", label: "AI Chat", icon: MessagesSquare, end: false },
  { to: "/documents", label: "Documents", icon: FileText, end: false },
  { to: "/evaluation", label: "Evaluation", icon: FlaskConical, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/chat": "AI Chat",
  "/documents": "Documents",
  "/evaluation": "Evaluation",
  "/settings": "Settings",
};

export function Layout() {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();

  const { data: stats } = useQuery({
    queryKey: queryKeys.stats,
    queryFn: api.stats,
    refetchInterval: POLL_INTERVAL_MS * 10,
  });

  const { data: readiness } = useQuery({
    queryKey: queryKeys.readiness,
    queryFn: api.readiness,
    refetchInterval: POLL_INTERVAL_MS * 15,
  });

  const title =
    pageTitles[location.pathname] ??
    (location.pathname.startsWith("/documents") ? "Document details" : "Compliance Copilot");

  const providerCheck = readiness?.checks?.find((check) => check.name === "llm_provider");

  return (
    <div className="flex min-h-dvh bg-canvas">
      {/* Skip link: the first tab stop on every page goes straight to content. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>

      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid size-8 place-items-center rounded-lg bg-accent text-white">
            <BarChart3 className="size-4" aria-hidden />
          </div>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-semibold text-ink">Compliance</p>
            <p className="truncate text-[13px] font-semibold text-ink">Intelligence</p>
          </div>
        </div>

        <nav aria-label="Main navigation" className="flex flex-col gap-0.5 px-3">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
                  isActive
                    ? "bg-accent-soft text-accent"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-3 border-t border-border p-4">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Corpus</p>
            <dl className="mt-1.5 space-y-1 text-[13px]">
              <div className="flex justify-between">
                <dt className="text-ink-3">Documents</dt>
                <dd className="tnum text-ink">{formatCount(stats?.documents?.active)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">Indexed chunks</dt>
                <dd className="tnum text-ink">{formatCount(stats?.index?.chunks)}</dd>
              </div>
            </dl>
            {stats?.index && stats.index.in_sync === false && (
              <p className="mt-2 text-[11px] text-danger">
                Index out of sync with the registry — re-index required.
              </p>
            )}
          </div>
          <p className="text-[11px] leading-snug text-ink-3">
            Reports what the indexed documents say. Not legal advice.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-5">
          <h1 className="truncate text-sm font-semibold text-ink">{title}</h1>

          <div className="flex items-center gap-2">
            {stats?.retrieval && (
              <Badge tone="neutral" className="hidden sm:inline-flex">
                k={String(stats.retrieval.top_k)}
                {stats.retrieval.rerank_enabled ? " · reranked" : " · RRF only"}
              </Badge>
            )}
            {providerCheck && (
              <Badge tone={providerCheck.ok ? "ok" : "danger"} className="hidden md:inline-flex">
                {providerCheck.detail}
              </Badge>
            )}
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              {theme === "dark" ? (
                <Sun className="size-4" aria-hidden />
              ) : (
                <Moon className="size-4" aria-hidden />
              )}
            </button>
          </div>
        </header>

        {/* Mobile navigation: the desktop sidebar is hidden below lg. */}
        <nav
          aria-label="Main navigation"
          className="flex gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 lg:hidden"
        >
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium",
                  isActive ? "bg-accent-soft text-accent" : "text-ink-2",
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>

        <main id="main" className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
