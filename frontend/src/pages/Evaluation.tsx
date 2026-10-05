/**
 * Evaluation dashboard.
 *
 * The page that separates this from a demo: retrieval quality is a measured, reproducible
 * number with a per-question drill-down, not an assertion.
 *
 * It is careful about two kinds of honesty:
 *  - deterministic metrics and LLM-judged metrics are visually separated and labelled,
 *  - failures are shown, not hidden, with the expected-vs-retrieved comparison for each.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play, TrendingUp } from "lucide-react";
import { ApiError, api, type EvaluationRunSummary } from "../lib/api";
import { POLL_INTERVAL_MS, queryKeys } from "../lib/queryKeys";
import { formatMetric, formatRelative, truncate } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Notice,
  Skeleton,
  Tabs,
  inputClass,
} from "../components/ui";
import { Stat } from "../components/domain";

const DETERMINISTIC_METRICS = [
  ["recall@1", "Recall@1"],
  ["recall@3", "Recall@3"],
  ["recall@5", "Recall@5"],
  ["recall@10", "Recall@10"],
  ["precision@3", "Precision@3"],
  ["precision@5", "Precision@5"],
  ["mrr", "MRR"],
  ["ndcg@5", "nDCG@5"],
  ["hit_rate@5", "Hit rate@5"],
  ["document_accuracy", "Document accuracy"],
  ["section_accuracy", "Section accuracy"],
] as const;

const GENERATION_METRICS = [
  ["citation_precision", "Citation precision"],
  ["citation_recall", "Citation recall"],
  ["keyword_score", "Keyword compliance"],
  ["numeric_score", "Numeric accuracy"],
  ["refusal_correct_rate", "Refusal accuracy"],
  ["forbidden_clean_rate", "Forbidden-content clean"],
] as const;

const JUDGED_METRICS = [
  ["faithfulness_llm_judged", "Faithfulness"],
  ["answer_relevance_llm_judged", "Answer relevance"],
] as const;

type TabId = "metrics" | "questions";

export default function EvaluationPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"retrieval_only" | "full">("retrieval_only");
  const [useJudge, setUseJudge] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("metrics");
  const [notice, setNotice] = useState<string | null>(null);

  const { data: datasets } = useQuery({
    queryKey: queryKeys.evaluationDatasets,
    queryFn: api.evaluationDatasets,
  });

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: queryKeys.evaluationRuns,
    queryFn: () => api.evaluationRuns(25),
    // Poll while a run is in flight (full mode runs in the background).
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === "running") ? POLL_INTERVAL_MS : false,
  });

  const activeRunId = selectedRunId ?? runs?.[0]?.id ?? null;

  const { data: run, error: runError } = useQuery({
    queryKey: queryKeys.evaluationRun(activeRunId ?? ""),
    queryFn: () => api.evaluationRun(activeRunId!),
    enabled: Boolean(activeRunId),
  });

  const start = useMutation({
    mutationFn: () =>
      api.startEvaluation({
        dataset: datasets?.[0]?.name ?? "aml_kyc_golden_v1",
        mode,
        judge: mode === "full" && useJudge,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.evaluationRuns });
      queryClient.invalidateQueries({ queryKey: queryKeys.stats });
      if ("id" in result) {
        setSelectedRunId(result.id);
        setNotice(null);
      } else {
        setNotice(result.message);
      }
    },
  });

  const dataset = datasets?.[0];
  const metrics = (run?.metrics ?? {}) as Record<string, number | Record<string, unknown>>;
  const byCategory = (metrics.by_category ?? {}) as Record<string, Record<string, number>>;
  const results = run?.results ?? [];

  return (
    <div className="space-y-4 p-5">
      {/* Run controls */}
      <Card>
        <CardHeader
          title="Run an evaluation"
          description={
            dataset
              ? `${dataset.name} · ${dataset.n_questions} labelled questions · ${dataset.refusal_cases} must-refuse cases`
              : "Loading dataset…"
          }
        />
        <div className="flex flex-wrap items-end gap-4 px-5 py-4">
          <Field label="Mode" htmlFor="eval-mode">
            <select
              id="eval-mode"
              value={mode}
              onChange={(event) => setMode(event.target.value as typeof mode)}
              className={`${inputClass} w-auto`}
            >
              <option value="retrieval_only">Retrieval only — deterministic, no LLM</option>
              <option value="full">Full — adds generation metrics</option>
            </select>
          </Field>

          {mode === "full" && (
            <label className="flex items-center gap-2 pb-2 text-[13px] text-ink-2">
              <input
                type="checkbox"
                checked={useJudge}
                onChange={(event) => setUseJudge(event.target.checked)}
                className="size-4 rounded border-border-strong"
              />
              Add LLM-judged faithfulness &amp; relevance
            </label>
          )}

          <Button
            variant="primary"
            loading={start.isPending}
            onClick={() => start.mutate()}
            icon={<Play className="size-4" aria-hidden />}
          >
            Run evaluation
          </Button>
        </div>

        <div className="border-t border-border px-5 py-3 text-[11px] text-ink-3">
          {mode === "retrieval_only" ? (
            <>
              Computes Recall@k, Precision@k, MRR, nDCG@5 and section accuracy by exact
              arithmetic against labelled section numbers. No LLM involved, so it is
              deterministic, free, and runs in seconds — this is the mode CI gates on.
            </>
          ) : (
            <>
              Adds citation precision/recall, keyword compliance, numeric accuracy and refusal
              accuracy — all exact. With the judge enabled it also reports LLM-judged
              faithfulness and relevance, which are indicative only and clearly separated below.
              Expect several minutes and a few hundred model calls.
            </>
          )}
        </div>
      </Card>

      {notice && (
        <Notice tone="accent" title="Evaluation started">
          {notice} Results appear below when it finishes.
        </Notice>
      )}
      {start.error && (
        <Notice tone="danger" title="Could not start the evaluation">
          {start.error instanceof Error ? start.error.message : "Unknown error"}
          {start.error instanceof ApiError && start.error.code === "index_not_ready" && (
            <p className="mt-1">Index a document first — there is nothing to evaluate against.</p>
          )}
        </Notice>
      )}

      {/* Run history */}
      <Card>
        <CardHeader title="Run history" description="Most recent first" />
        {runsLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-9" />
            ))}
          </div>
        ) : !runs?.length ? (
          <EmptyState
            icon={<FlaskConical className="size-7" aria-hidden />}
            title="No evaluation runs yet"
            description="Run the golden set above to measure retrieval quality."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <caption className="sr-only">Evaluation run history</caption>
              <thead>
                <tr className="border-b border-border bg-surface-2 text-left text-ink-3">
                  <th scope="col" className="px-4 py-2 font-medium">Started</th>
                  <th scope="col" className="px-4 py-2 font-medium">Mode</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">n</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">recall@5</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">MRR</th>
                  <th scope="col" className="px-4 py-2 font-medium">Rerank</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((item) => (
                  <RunRow
                    key={item.id}
                    run={item}
                    active={item.id === activeRunId}
                    onSelect={() => {
                      setSelectedRunId(item.id);
                      setTab("metrics");
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Selected run */}
      {runError ? (
        <ErrorState message={runError instanceof Error ? runError.message : "Could not load run."} />
      ) : run ? (
        <Card>
          <CardHeader
            title={`Run ${run.id}`}
            description={`${run.dataset} · ${run.mode} · ${formatRelative(run.started_at)}`}
            actions={
              run.config?.rerank_enabled ? (
                <Badge tone="accent">reranked</Badge>
              ) : (
                <Badge tone="neutral">RRF only</Badge>
              )
            }
          />

          {run.status === "running" ? (
            <div className="px-5 py-8 text-center text-[13px] text-ink-2" role="status">
              Evaluation in progress… this page updates automatically.
            </div>
          ) : run.status === "failed" ? (
            <ErrorState title="Run failed" message={run.error ?? "Unknown failure"} />
          ) : (
            <>
              <div className="px-5 pt-3">
                <Tabs
                  tabs={[
                    { id: "metrics", label: "Metrics" },
                    { id: "questions", label: "Per-question", count: results.length },
                  ] as const}
                  active={tab}
                  onChange={(id) => setTab(id as TabId)}
                />
              </div>

              {tab === "metrics" ? (
                <div className="space-y-5 p-5">
                  {/* Headline */}
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <Stat
                      label="Recall@5"
                      value={formatMetric(metrics["recall@5"] as number)}
                      hint="labelled section in top 5"
                    />
                    <Stat label="MRR" value={formatMetric(metrics.mrr as number)} hint="rank of first hit" />
                    <Stat label="nDCG@5" value={formatMetric(metrics["ndcg@5"] as number)} hint="order-sensitive" />
                    <Stat
                      label="Section accuracy"
                      value={formatMetric(metrics.section_accuracy as number)}
                      hint="right document AND section"
                    />
                  </div>

                  <MetricTable
                    title="Retrieval (deterministic — exact arithmetic)"
                    rows={DETERMINISTIC_METRICS}
                    metrics={metrics}
                  />

                  {GENERATION_METRICS.some(([key]) => key in metrics) && (
                    <MetricTable
                      title="Generation (deterministic — exact)"
                      rows={GENERATION_METRICS}
                      metrics={metrics}
                      extra={
                        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-3">
                          <span>correct refusals: {String(metrics.correct_refusal_count ?? "–")}</span>
                          <span>over-refusals: {String(metrics.over_refusal_count ?? "–")}</span>
                          <span>missed refusals: {String(metrics.missed_refusal_count ?? "–")}</span>
                        </div>
                      }
                    />
                  )}

                  {JUDGED_METRICS.some(([key]) => key in metrics) && (
                    <div>
                      <MetricTable
                        title="Generation (LLM-judged — indicative, not ground truth)"
                        rows={JUDGED_METRICS}
                        metrics={metrics}
                      />
                      <p className="mt-2 text-[11px] text-ink-3">
                        Judged at temperature 0 with a versioned prompt and per-claim reasoning
                        persisted. Treated as indicative: the deterministic metrics above are the
                        ones to trust.
                      </p>
                    </div>
                  )}

                  {Object.keys(byCategory).length > 0 && (
                    <div>
                      <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
                        By category
                      </h3>
                      <p className="mt-1 text-[11px] text-ink-3">
                        Aggregates hide category-level weakness — this is where a configuration
                        change proves whether it helped the questions that were failing.
                      </p>
                      <div className="mt-2 overflow-x-auto rounded-lg border border-border">
                        <table className="w-full text-[13px]">
                          <thead>
                            <tr className="border-b border-border bg-surface-2 text-left text-ink-3">
                              <th scope="col" className="px-3 py-2 font-medium">Category</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">n</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">recall@5</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">precision@3</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">MRR</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">section acc.</th>
                              <th scope="col" className="px-3 py-2 text-right font-medium">refusal acc.</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(byCategory).map(([category, row]) => (
                              <tr key={category} className="border-b border-border last:border-0">
                                <td className="px-3 py-2 font-medium text-ink">{category}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{row.n}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{formatMetric(row["recall@5"])}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{formatMetric(row["precision@3"])}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{formatMetric(row.mrr)}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{formatMetric(row.section_accuracy)}</td>
                                <td className="tnum px-3 py-2 text-right text-ink-2">{formatMetric(row.refusal_correct_rate)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  <details className="rounded-lg border border-border bg-surface-2 p-3">
                    <summary className="cursor-pointer text-[13px] font-medium text-ink">
                      Run configuration
                    </summary>
                    <dl className="mt-2 grid gap-x-6 gap-y-1 text-[11px] sm:grid-cols-2">
                      {Object.entries(run.config ?? {}).map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-3">
                          <dt className="text-ink-3">{key}</dt>
                          <dd className="truncate font-mono text-ink">{String(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                </div>
              ) : (
                <PerQuestion results={results} />
              )}
            </>
          )}
        </Card>
      ) : null}
    </div>
  );
}

function RunRow({
  run,
  active,
  onSelect,
}: {
  run: EvaluationRunSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const metrics = (run.metrics ?? {}) as Record<string, number>;
  return (
    <tr
      className={`cursor-pointer border-b border-border last:border-0 hover:bg-surface-2 ${active ? "bg-accent-soft" : ""}`}
      onClick={onSelect}
    >
      <td className="px-4 py-2 text-ink-2">{formatRelative(run.started_at)}</td>
      <td className="px-4 py-2 text-ink-2">{run.mode}</td>
      <td className="tnum px-4 py-2 text-right text-ink-2">{run.n_questions}</td>
      <td className="tnum px-4 py-2 text-right text-ink">{formatMetric(metrics["recall@5"])}</td>
      <td className="tnum px-4 py-2 text-right text-ink">{formatMetric(metrics.mrr)}</td>
      <td className="px-4 py-2">
        {run.config?.rerank_enabled ? (
          <Badge tone="accent">on</Badge>
        ) : (
          <Badge tone="neutral">off</Badge>
        )}
      </td>
      <td className="px-4 py-2">
        <Badge
          tone={run.status === "completed" ? "ok" : run.status === "failed" ? "danger" : "accent"}
        >
          {run.status}
        </Badge>
      </td>
    </tr>
  );
}

/** Per-question drill-down, failures first — the useful order when diagnosing. */
function PerQuestion({ results }: { results: Array<Record<string, unknown>> }) {
  const [onlyFailures, setOnlyFailures] = useState(true);

  const rows = results
    .map((result) => ({
      id: String(result.question_id),
      question: String(result.question ?? ""),
      category: String(result.category ?? ""),
      metrics: (result.metrics ?? {}) as Record<string, number | boolean | string[]>,
      detail: (result.detail ?? {}) as Record<string, unknown>,
      expectedDocuments: (result.expected_documents ?? []) as string[],
      expectedSections: (result.expected_sections ?? []) as string[],
    }))
    .sort((a, b) => Number(a.metrics["recall@5"] ?? 1) - Number(b.metrics["recall@5"] ?? 1));

  const failing = rows.filter((row) => Number(row.metrics["recall@5"] ?? 1) < 1);
  const visible = onlyFailures && failing.length > 0 ? failing : rows;

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No per-question results"
        description="This run stored no individual question results."
      />
    );
  }

  return (
    <div className="p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[13px] text-ink-2">
          {failing.length === 0 ? (
            <span className="inline-flex items-center gap-1.5 text-ok">
              <TrendingUp className="size-4" aria-hidden />
              Every question retrieved its labelled sections.
            </span>
          ) : (
            `${failing.length} of ${rows.length} questions did not retrieve every labelled section.`
          )}
        </p>
        {failing.length > 0 && (
          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            <input
              type="checkbox"
              checked={onlyFailures}
              onChange={(event) => setOnlyFailures(event.target.checked)}
              className="size-4 rounded border-border-strong"
            />
            Only incomplete
          </label>
        )}
      </div>

      <ul className="space-y-2">
        {visible.map((row) => {
          const recall = Number(row.metrics["recall@5"] ?? 0);
          const retrieved = (row.detail.retrieved ?? []) as Array<{ document?: string; section?: string }>;
          return (
            <li key={row.id} className="rounded-lg border border-border">
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border bg-surface-2 px-3.5 py-2">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-ink">
                    <span className="font-mono text-[11px] text-ink-3">{row.id}</span>{" "}
                    {truncate(row.question, 110)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Badge tone="neutral" className="text-[10px]">{row.category}</Badge>
                  <Badge tone={recall >= 1 ? "ok" : recall > 0 ? "warn" : "danger"} className="text-[10px]">
                    recall@5 {formatMetric(recall, 2)}
                  </Badge>
                  {row.metrics.refusal_correct === false && (
                    <Badge tone="danger" className="text-[10px]">refusal wrong</Badge>
                  )}
                </div>
              </div>
              <div className="grid gap-3 px-3.5 py-2.5 text-[11px] sm:grid-cols-2">
                <div>
                  <p className="font-medium text-ink-3">Expected</p>
                  <p className="mt-0.5 text-ink-2">
                    {row.expectedDocuments.length
                      ? `${row.expectedDocuments.join(", ")} ${row.expectedSections.length ? `§${row.expectedSections.join(", §")}` : ""}`
                      : "no labelled sections (must refuse)"}
                  </p>
                </div>
                <div>
                  <p className="font-medium text-ink-3">Retrieved</p>
                  <ul className="mt-0.5 space-y-0.5 text-ink-2">
                    {retrieved.slice(0, 4).map((item, index) => (
                      <li key={index} className="truncate">
                        {item.document} {item.section ? `§${item.section}` : ""}
                      </li>
                    ))}
                    {retrieved.length === 0 && <li>nothing retrieved</li>}
                  </ul>
                </div>
              </div>
              {typeof row.detail.answer === "string" && row.detail.answer && (
                <details className="border-t border-border px-3.5 py-2">
                  <summary className="cursor-pointer text-[11px] text-ink-3">Answer given</summary>
                  <p className="mt-1.5 text-[13px] text-ink-2">{String(row.detail.answer)}</p>
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function MetricTable({
  title,
  rows,
  metrics,
  extra,
}: {
  title: string;
  rows: ReadonlyArray<readonly [string, string]>;
  metrics: Record<string, unknown>;
  extra?: React.ReactNode;
}) {
  const present = rows.filter(([key]) => key in metrics);
  if (present.length === 0) return null;

  return (
    <div>
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{title}</h3>
      <dl className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {present.map(([key, label]) => (
          <div key={key} className="flex items-baseline justify-between gap-3 border-b border-border pb-1">
            <dt className="text-[13px] text-ink-2">{label}</dt>
            <dd className="tnum text-[13px] font-semibold text-ink">
              {formatMetric(metrics[key] as number)}
            </dd>
          </div>
        ))}
      </dl>
      {extra}
    </div>
  );
}
