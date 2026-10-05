/**
 * Domain components: the pieces that encode compliance-specific meaning.
 *
 * These are where the product's honesty lives in the UI — an evidence band must never read
 * as a confidence score, a conflict must never be collapsed into one answer, and a status
 * must never be conveyed by colour alone.
 */

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  Clock,
  FileText,
  Loader2,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { Conflict, DocumentStatus, Evidence, EvidenceBand } from "../lib/api";
import { cn, formatMetric } from "../lib/format";
import { Badge } from "./ui";

// --- Evidence ---------------------------------------------------------------

const bandConfig: Record<
  EvidenceBand,
  { label: string; tone: "ok" | "warn" | "caution" | "neutral"; icon: typeof CheckCircle2 }
> = {
  strong: { label: "Well supported", tone: "ok", icon: CheckCircle2 },
  moderate: { label: "Supported — verify citations", tone: "warn", icon: CircleAlert },
  weak: { label: "Limited evidence", tone: "caution", icon: AlertTriangle },
  insufficient: { label: "No sufficient evidence", tone: "neutral", icon: CircleHelp },
};

/**
 * Evidence strength, with the underlying signals on demand.
 *
 * Deliberately never rendered as a percentage: the backend derives this band from retrieval
 * signals by a published rule, and presenting it as a probability would misrepresent it.
 * The disclaimer travels with the data from the API and is shown verbatim.
 */
export function EvidenceBadge({ evidence }: { evidence: Evidence }) {
  const [open, setOpen] = useState(false);
  const band = evidence.band ?? "insufficient";
  const config = bandConfig[band];
  const Icon = config.icon;
  const signals = evidence.signals;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={config.tone} icon={<Icon className="size-3.5" aria-hidden />}>
          {config.label}
        </Badge>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="text-xs text-ink-3 underline decoration-dotted underline-offset-2 hover:text-ink-2"
        >
          {open ? "Hide" : "Show"} evidence signals
        </button>
      </div>

      {open && (
        <div className="space-y-2 rounded-lg border border-border bg-surface-2 p-3 text-xs">
          {evidence.basis && <p className="text-ink-2">{evidence.basis}</p>}
          {signals && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
              <Signal label="Top passage score" value={formatMetric(signals.top_score, 3)} />
              <Signal label="Margin over next" value={formatMetric(signals.score_margin, 3)} />
              <Signal label="Supporting passages" value={String(signals.supporting_chunks ?? 0)} />
              <Signal label="Distinct documents" value={String(signals.distinct_documents ?? 0)} />
              <Signal
                label="Context cited"
                value={formatMetric(signals.cited_fraction_of_context, 2)}
              />
              <Signal label="Refusal" value={signals.answer_is_refusal ? "yes" : "no"} />
            </dl>
          )}
          <p className="border-t border-border pt-2 text-[11px] text-ink-3">
            {evidence.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}

function Signal({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-3">{label}</dt>
      <dd className="tnum font-mono text-[11px] text-ink">{value}</dd>
    </div>
  );
}

// --- Conflicts --------------------------------------------------------------

/**
 * Surfaces a version conflict instead of letting the answer silently pick a side.
 * Rendered above the answer, because knowing two versions disagree changes how the whole
 * answer should be read.
 */
export function ConflictCallout({ conflicts }: { conflicts: Conflict[] }) {
  if (conflicts.length === 0) return null;

  return (
    <div className="space-y-3">
      {conflicts.map((conflict, index) => (
        <div
          key={index}
          role="alert"
          className="rounded-lg border border-warn/35 bg-warn-soft p-3.5 text-[13px]"
        >
          <p className="flex items-center gap-2 font-semibold text-warn">
            <AlertTriangle className="size-4" aria-hidden />
            Conflicting requirements found across document versions
          </p>
          <p className="mt-1.5 text-ink-2">{conflict.description}</p>
          <ul className="mt-2.5 space-y-1">
            {(conflict.sources ?? []).map((source) => (
              <li key={`${source.document_id}-${source.version}`} className="flex flex-wrap items-center gap-2">
                <FileText className="size-3.5 shrink-0 text-ink-3" aria-hidden />
                <span className="text-ink">
                  {source.document_title}
                  {source.version && <span className="text-ink-2"> v{source.version}</span>}
                </span>
                {source.effective_date && (
                  <span className="tnum text-xs text-ink-3">
                    effective {source.effective_date}
                  </span>
                )}
                {source.section && <span className="text-xs text-ink-3">§{source.section}</span>}
                {source.is_most_recent && (
                  <Badge tone="ok" className="text-[10px]">
                    most recent
                  </Badge>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2.5 text-[11px] text-ink-3">
            Detected structurally from document metadata (version and effective date), not
            inferred by the model.
          </p>
        </div>
      ))}
    </div>
  );
}

// --- Document status --------------------------------------------------------

const statusConfig: Record<
  DocumentStatus | string,
  { label: string; tone: "ok" | "warn" | "danger" | "neutral" | "accent"; icon: typeof CheckCircle2 }
> = {
  indexed: { label: "Indexed", tone: "ok", icon: CheckCircle2 },
  processing: { label: "Processing", tone: "accent", icon: Loader2 },
  failed: { label: "Failed", tone: "danger", icon: XCircle },
  inactive: { label: "Inactive", tone: "neutral", icon: Clock },
};

/** Status is always icon + label, never colour alone. */
export function StatusPill({ status }: { status: DocumentStatus | string }) {
  const config = statusConfig[status] ?? {
    label: status,
    tone: "neutral" as const,
    icon: CircleHelp,
  };
  const Icon = config.icon;
  return (
    <Badge tone={config.tone} icon={<Icon className={cn("size-3.5", status === "processing" && "animate-spin")} aria-hidden />}>
      {config.label}
    </Badge>
  );
}

/** Injection-scan flags, framed honestly: a review prompt, not a verdict. */
export function InjectionFlags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null;
  return (
    <div className="rounded-lg border border-caution/35 bg-caution-soft p-3 text-[13px]">
      <p className="flex items-center gap-2 font-semibold text-caution">
        <ShieldAlert className="size-4" aria-hidden />
        {flags.length} span{flags.length === 1 ? "" : "s"} flagged for review
      </p>
      <p className="mt-1 text-ink-2">
        This document contains text that resembles a prompt-injection attempt. Answers are
        protected structurally regardless — citations are resolved against retrieved passages
        server-side, so injected instructions cannot fabricate a citation.
      </p>
      <ul className="mt-2 space-y-1 font-mono text-[11px] text-ink-2">
        {flags.slice(0, 5).map((flag, index) => (
          <li key={index} className="truncate">
            {flag}
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- Metric tile ------------------------------------------------------------

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  const valueTone = {
    neutral: "text-ink",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  }[tone];
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3.5">
      <p className="text-xs font-medium text-ink-3">{label}</p>
      <p className={cn("tnum mt-1 text-2xl font-semibold tracking-tight", valueTone)}>{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-ink-3">{hint}</p>}
    </div>
  );
}
