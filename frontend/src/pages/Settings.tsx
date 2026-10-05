/**
 * Settings.
 *
 * Only exposes what makes sense for a demonstration: provider, model, retrieval parameters,
 * reranking, temperature. Overrides are session-scoped on the server and never written to
 * disk, which the page states plainly so nobody mistakes this for editing a deployment.
 *
 * Secrets are never displayed — the API returns `groq_configured: true`, never the key.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { api, getApiKey, setApiKey, type SettingsPatchRequest } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { formatMetric } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorState,
  Field,
  Notice,
  Skeleton,
  inputClass,
} from "../components/ui";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.settings,
  });

  const [draft, setDraft] = useState<SettingsPatchRequest>({});
  const [apiKeyDraft, setApiKeyDraft] = useState(getApiKey() ?? "");
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: (body: SettingsPatchRequest) => api.updateSettings(body),
    onSuccess: () => {
      setSaved(true);
      setDraft({});
      queryClient.invalidateQueries({ queryKey: queryKeys.settings });
      queryClient.invalidateQueries({ queryKey: queryKeys.stats });
      window.setTimeout(() => setSaved(false), 4000);
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (error || !settings) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Could not load settings."}
        onRetry={() => void refetch()}
      />
    );
  }

  const value = <K extends keyof SettingsPatchRequest>(
    key: K,
    fallback: NonNullable<SettingsPatchRequest[K]>,
  ): NonNullable<SettingsPatchRequest[K]> => (draft[key] ?? fallback) as NonNullable<SettingsPatchRequest[K]>;

  const isDirty = Object.keys(draft).length > 0;

  return (
    <div className="max-w-3xl space-y-4 p-5">
      {saved && (
        <Notice tone="ok" title="Settings applied">
          Active for this server process. Nothing was written to disk.
        </Notice>
      )}
      {save.error && (
        <Notice tone="danger" title="Could not apply settings">
          {save.error instanceof Error ? save.error.message : "Unknown error"}
        </Notice>
      )}

      {/* Model */}
      <Card>
        <CardHeader
          title="Language model"
          description="Generation provider and model for new questions"
        />
        <div className="space-y-4 px-5 py-4">
          <Field label="Provider" htmlFor="provider" hint="Ollama runs fully offline with no API key.">
            <select
              id="provider"
              value={value("llm_provider", settings.llm_provider as "groq" | "ollama")}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  llm_provider: event.target.value as "groq" | "ollama",
                }))
              }
              className={inputClass}
            >
              <option value="groq">Groq — hosted, fast</option>
              <option value="ollama">Ollama — local, offline</option>
            </select>
          </Field>

          <Field
            label="Model"
            htmlFor="model"
            hint="The model id is configuration, never hardcoded — swapping it touches nothing in the pipeline."
          >
            <input
              id="model"
              value={value("llm_model", settings.llm_model)}
              onChange={(event) =>
                setDraft((current) => ({ ...current, llm_model: event.target.value }))
              }
              className={`${inputClass} font-mono text-[13px]`}
            />
          </Field>

          <Field
            label={`Temperature — ${formatMetric(value("temperature", settings.temperature), 2)}`}
            htmlFor="temperature"
            hint="0 is the default. Compliance answers should be reproducible, so raising this is rarely right."
          >
            <input
              id="temperature"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={value("temperature", settings.temperature)}
              onChange={(event) =>
                setDraft((current) => ({ ...current, temperature: Number(event.target.value) }))
              }
              className="w-full accent-[var(--color-accent)]"
            />
          </Field>

          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            <Badge tone={settings.groq_configured ? "ok" : "neutral"}>
              {settings.groq_configured ? "Groq key configured" : "No Groq key configured"}
            </Badge>
            <Badge tone="neutral">Ollama at {settings.ollama_base_url}</Badge>
          </div>
        </div>
      </Card>

      {/* Retrieval */}
      <Card>
        <CardHeader title="Retrieval" description="How passages are found and ranked" />
        <div className="space-y-4 px-5 py-4">
          <Field
            label={`Passages per question (top-k) — ${value("top_k", settings.retrieval_top_k)}`}
            htmlFor="top-k"
            hint="Measured: k=5 balances recall and context size; 8–10 helps questions spanning several documents."
          >
            <input
              id="top-k"
              type="range"
              min={1}
              max={20}
              step={1}
              value={value("top_k", settings.retrieval_top_k)}
              onChange={(event) =>
                setDraft((current) => ({ ...current, top_k: Number(event.target.value) }))
              }
              className="w-full accent-[var(--color-accent)]"
            />
          </Field>

          <div className="flex items-start gap-3 rounded-lg border border-border bg-surface-2 p-3">
            <input
              id="rerank"
              type="checkbox"
              checked={value("rerank_enabled", settings.rerank_enabled)}
              onChange={(event) =>
                setDraft((current) => ({ ...current, rerank_enabled: event.target.checked }))
              }
              className="mt-0.5 size-4 rounded border-border-strong"
            />
            <label htmlFor="rerank" className="text-[13px]">
              <span className="font-medium text-ink">Cross-encoder reranking</span>
              <span className="mt-0.5 block text-ink-2">
                Enabled by default because the golden set measured a material gain — recall@1
                0.774 → 0.870, MRR 0.776 → 0.863. Turning it off reproduces the RRF-only baseline
                exactly, which is useful for comparison but not for quality.
              </span>
              <span className="mt-1 block font-mono text-[11px] text-ink-3">
                {settings.rerank_model}
              </span>
            </label>
          </div>

          <dl className="grid gap-x-6 gap-y-1.5 border-t border-border pt-3 text-[13px] sm:grid-cols-2">
            <ReadOnly label="Embedding model" value={settings.embedding_model} mono />
            <ReadOnly
              label="Query instruction prefix"
              value={settings.embedding_query_prefix_enabled ? "enabled" : "disabled"}
            />
            <ReadOnly label="Candidate pool" value={String(settings.retrieval_candidate_pool)} />
            <ReadOnly label="RRF k" value={String(settings.rrf_k)} />
            <ReadOnly label="Context budget" value={`${settings.context_max_tokens} tokens`} />
            <ReadOnly
              label="Evidence floors"
              value={`refuse < ${settings.evidence_floors.refusal} · moderate ≥ ${settings.evidence_floors.moderate} · strong ≥ ${settings.evidence_floors.strong}`}
            />
          </dl>
          <p className="text-[11px] text-ink-3">
            The read-only values are deployment configuration (environment variables), not
            session settings — changing an embedding model requires re-indexing the corpus, so it
            is deliberately not adjustable from the UI.
          </p>
        </div>
      </Card>

      {/* Access */}
      <Card>
        <CardHeader
          title="API access"
          description="Used for write operations when the server requires a key"
        />
        <div className="space-y-4 px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={settings.auth_enabled ? "ok" : "warn"} icon={<ShieldCheck className="size-3.5" aria-hidden />}>
              {settings.auth_enabled ? "API key required" : "Open — no API key configured"}
            </Badge>
            <Badge tone="neutral">{settings.rate_limit_per_minute} requests/min</Badge>
            <Badge tone="neutral">max {settings.max_upload_mb} MB per file</Badge>
          </div>

          {!settings.auth_enabled && (
            <Notice tone="warn" title="This server is running open">
              No <code>API_KEY</code> is configured, so every request is accepted. That is the
              documented default for local development only — set <code>API_KEY</code> in the
              environment before exposing this service.
            </Notice>
          )}

          <Field
            label="Your API key"
            htmlFor="api-key"
            hint="Stored in this browser only and sent as the X-API-Key header. Never logged or returned by the API."
          >
            <div className="flex gap-2">
              <input
                id="api-key"
                type="password"
                value={apiKeyDraft}
                onChange={(event) => setApiKeyDraft(event.target.value)}
                placeholder={settings.auth_enabled ? "Required for uploads and deletes" : "Not required"}
                className={`${inputClass} font-mono text-[13px]`}
              />
              <Button
                icon={<KeyRound className="size-4" aria-hidden />}
                onClick={() => {
                  setApiKey(apiKeyDraft || null);
                  setSaved(true);
                  window.setTimeout(() => setSaved(false), 3000);
                }}
              >
                Save key
              </Button>
            </div>
          </Field>

          <p className="text-[11px] text-ink-3">
            Accepted upload types: {settings.allowed_file_types.join(", ")}. Files are validated
            by content signature, not just by extension.
          </p>
        </div>
      </Card>

      {/* Actions */}
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-ink-3">
          Changes apply to the running server process and are never persisted to disk.
        </p>
        <div className="flex gap-2">
          <Button
            disabled={!isDirty}
            onClick={() => setDraft({})}
            icon={<RotateCcw className="size-4" aria-hidden />}
          >
            Reset
          </Button>
          <Button
            variant="primary"
            disabled={!isDirty}
            loading={save.isPending}
            onClick={() => save.mutate(draft)}
            icon={<Save className="size-4" aria-hidden />}
          >
            Apply changes
          </Button>
        </div>
      </div>
    </div>
  );
}

function ReadOnly({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-3">{label}</dt>
      <dd className={mono ? "truncate font-mono text-[11px] text-ink" : "text-right text-ink"}>
        {value}
      </dd>
    </div>
  );
}
