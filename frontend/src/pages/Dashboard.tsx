/**
 * Dashboard.
 *
 * Every figure here is measured by the backend from the registry, the query log and the
 * indices. Nothing is synthesised for display: where a value is genuinely unknown (no
 * queries yet, no evaluation run yet) the UI says so rather than showing a plausible zero.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  FlaskConical,
  MessagesSquare,
  XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import { POLL_INTERVAL_MS, queryKeys } from "../lib/queryKeys";
import { formatCount, formatMetric, formatMs, formatPercent, formatRelative } from "../lib/format";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from "../components/ui";
import { Stat } from "../components/domain";

export default function DashboardPage() {
  const {
    data: stats,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.stats,
    queryFn: api.stats,
    refetchInterval: POLL_INTERVAL_MS * 5,
  });

  const { data: readiness } = useQuery({
    queryKey: queryKeys.readiness,
    queryFn: api.readiness,
    refetchInterval: POLL_INTERVAL_MS * 10,
  });

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[88px]" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error || !stats) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Could not load dashboard statistics."}
        onRetry={() => void refetch()}
      />
    );
  }

  // These are required fields on StatsResponse, so no defensive fallback is needed —
  // and adding one would widen the type back to `{}` and lose every field.
  const { queries, index, documents } = stats;
  const hasQueries = queries.queries_total > 0;

  return (
    <div className="space-y-5 p-5">
      {/* Corpus + index */}
      <section aria-labelledby="corpus-heading" className="space-y-3">
        <h2 id="corpus-heading" className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
          Corpus
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Active documents"
            value={formatCount(documents.active)}
            hint={`${formatCount(documents.total)} total`}
          />
          <Stat label="Indexed chunks" value={formatCount(index.chunks)} hint="searchable passages" />
          <Stat
            label="Vectors"
            value={formatCount(index.vectors)}
            hint={index.in_sync ? "in sync with registry" : "OUT OF SYNC"}
            tone={index.in_sync ? "neutral" : "danger"}
          />
          <Stat
            label="Conversations"
            value={formatCount(stats.conversations?.total ?? 0)}
            hint="transcripts stored"
          />
        </div>

        {documents.failed ? (
          <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
            <XCircle className="size-4 shrink-0" aria-hidden />
            <span>
              {documents.failed} document{documents.failed === 1 ? "" : "s"} failed to index.
            </span>
            <Link to="/documents?status=failed" className="ml-auto underline">
              Review
            </Link>
          </div>
        ) : null}
      </section>

      {/* Query performance */}
      <section aria-labelledby="queries-heading" className="space-y-3">
        <h2 id="queries-heading" className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
          Query performance
        </h2>
        {!hasQueries ? (
          <Card>
            <EmptyState
              icon={<MessagesSquare className="size-7" aria-hidden />}
              title="No queries recorded yet"
              description="Latency percentiles and refusal rate appear here once questions have been asked."
              action={
                <Link to="/chat">
                  <Button size="sm" variant="primary">
                    Ask a question
                  </Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Queries processed" value={formatCount(queries.queries_total)} />
            <Stat label="p50 latency" value={formatMs(queries.p50_total_ms)} hint="end to end" />
            <Stat label="p95 latency" value={formatMs(queries.p95_total_ms)} hint="end to end" />
            <Stat
              label="Refusal rate"
              value={formatPercent(queries.refusal_rate, 0)}
              hint="insufficient evidence"
              tone="neutral"
            />
          </div>
        )}
        {hasQueries && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Avg retrieval" value={formatMs(queries.avg_retrieval_ms)} />
            <Stat label="Avg generation" value={formatMs(queries.avg_llm_ms)} />
            <Stat
              label="Errors"
              value={formatCount(queries.errors)}
              hint={formatPercent(queries.error_rate, 1)}
              tone={queries.errors ? "warn" : "neutral"}
            />
          </div>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Retrieval configuration */}
        <Card>
          <CardHeader
            title="Retrieval configuration"
            description="The settings that produced the figures above"
            actions={
              <Link to="/settings">
                <Button size="sm" variant="ghost">
                  Change
                </Button>
              </Link>
            }
          />
          <dl className="divide-y divide-border">
            <Row label="Embedding model" value={index.embedding_model ?? "–"} mono />
            <Row label="Top-k passages" value={String(stats.retrieval?.top_k ?? "–")} />
            <Row label="Candidate pool" value={String(stats.retrieval?.candidate_pool ?? "–")} />
            <Row label="RRF k" value={String(stats.retrieval?.rrf_k ?? "–")} />
            <Row
              label="Reranking"
              value={
                stats.retrieval?.rerank_enabled
                  ? (stats.retrieval?.rerank_model ?? "enabled")
                  : "disabled (RRF-only baseline)"
              }
              mono={Boolean(stats.retrieval?.rerank_enabled)}
            />
          </dl>
        </Card>

        {/* System health */}
        <Card>
          <CardHeader title="System health" description="Live readiness checks" />
          <ul className="divide-y divide-border">
            {(readiness?.checks ?? []).map((check) => (
              <li key={check.name} className="flex items-start gap-2.5 px-5 py-2.5 text-[13px]">
                {check.ok ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
                ) : (
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
                )}
                <div className="min-w-0">
                  <p className="font-medium text-ink">{check.name.replace(/_/g, " ")}</p>
                  <p className="truncate text-ink-3">{check.detail}</p>
                </div>
              </li>
            ))}
            {!readiness && <li className="px-5 py-3 text-[13px] text-ink-3">Checking…</li>}
          </ul>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Latest evaluation */}
        <Card>
          <CardHeader
            title="Latest evaluation"
            description="Measured retrieval quality"
            actions={
              <Link to="/evaluation">
                <Button size="sm" variant="ghost" icon={<FlaskConical className="size-4" aria-hidden />}>
                  Open
                </Button>
              </Link>
            }
          />
          {!stats.evaluation?.latest ? (
            <EmptyState
              icon={<FlaskConical className="size-6" aria-hidden />}
              title="No evaluation run yet"
              description="Run the golden set to measure retrieval quality."
              action={
                <Link to="/evaluation">
                  <Button size="sm" variant="primary">
                    Run evaluation
                  </Button>
                </Link>
              }
            />
          ) : (
            <div className="px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">{String(stats.evaluation.latest.dataset)}</Badge>
                <Badge tone="neutral">{String(stats.evaluation.latest.mode)}</Badge>
                <span className="text-[11px] text-ink-3">
                  {formatRelative(String(stats.evaluation.latest.started_at))}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metric label="recall@5" value={stats.evaluation.latest.metrics?.["recall@5"]} />
                <Metric label="MRR" value={stats.evaluation.latest.metrics?.mrr} />
                <Metric label="nDCG@5" value={stats.evaluation.latest.metrics?.["ndcg@5"]} />
                <Metric
                  label="section acc."
                  value={stats.evaluation.latest.metrics?.section_accuracy}
                />
              </dl>
            </div>
          )}
        </Card>

        {/* Recent activity */}
        <Card>
          <CardHeader
            title="Recent activity"
            description="Questions are recorded by hash, never by content"
          />
          {!stats.recent_activity?.length ? (
            <EmptyState
              icon={<Activity className="size-6" aria-hidden />}
              title="No activity yet"
              description="Query activity appears here as questions are asked."
            />
          ) : (
            <ul className="divide-y divide-border">
              {stats.recent_activity.slice(0, 8).map((entry, position) => (
                <li
                  key={`${entry.created_at}-${position}`}
                  className="flex items-center gap-3 px-5 py-2.5 text-[13px]"
                >
                  <span className="tnum shrink-0 font-mono text-[11px] text-ink-3">
                    {String(entry.question_hash).slice(0, 8)}
                  </span>
                  <span className="flex-1 truncate text-ink-2">
                    {entry.n_cited ? `${entry.n_cited} citation${entry.n_cited === 1 ? "" : "s"}` : "no citations"}
                    {entry.evidence_band ? ` · ${entry.evidence_band}` : ""}
                  </span>
                  {entry.refused ? <Badge tone="neutral">refused</Badge> : null}
                  {entry.error_code ? <Badge tone="danger">error</Badge> : null}
                  <span className="tnum shrink-0 text-[11px] text-ink-3">
                    {formatMs(Number(entry.total_ms))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="flex items-center gap-2 text-[11px] text-ink-3">
        <Database className="size-3.5" aria-hidden />
        All figures are measured from the document registry, the query log and the live indices.
        <Link to="/documents" className="ml-1 inline-flex items-center gap-1 underline">
          <FileText className="size-3.5" aria-hidden />
          Manage documents
        </Link>
      </p>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-2.5 text-[13px]">
      <dt className="text-ink-3">{label}</dt>
      <dd className={mono ? "truncate font-mono text-[11px] text-ink" : "text-ink"}>{value}</dd>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="tnum text-lg font-semibold text-ink">
        {typeof value === "number" ? formatMetric(value) : "–"}
      </dd>
    </div>
  );
}
