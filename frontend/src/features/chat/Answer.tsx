/**
 * Answer rendering: markdown with GFM tables, inline citation chips, and a source panel.
 *
 * The citation chips are the product. An answer a compliance officer cannot verify is worth
 * nothing, so `[1]` in the prose is a real button that opens the exact retrieved passage with
 * its document, version, section and retrieval scores.
 */

import { memo, useMemo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, FileText, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { Citation } from "../../lib/api";
import { cn, formatMetric } from "../../lib/format";
import { Badge, Button } from "../../components/ui";

/**
 * Renders answer markdown, replacing `[n]` references with clickable chips.
 *
 * The server has already resolved and renumbered markers, so anything matching `[n]` here
 * with a known index is guaranteed to map to a real retrieved passage. Unknown indices are
 * left as plain text rather than linked to nothing.
 */
export const AnswerBody = memo(function AnswerBody({
  content,
  citations,
  onCitationClick,
}: {
  content: string;
  citations: Citation[];
  onCitationClick: (citation: Citation) => void;
}) {
  const byIndex = useMemo(
    () => new Map(citations.map((citation) => [citation.index, citation])),
    [citations],
  );

  return (
    <div className="answer-prose text-ink">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          // GFM tables are common in policy answers (risk bands, review frequencies) and
          // must scroll inside their own container rather than widening the page.
          table: ({ children }) => (
            <div className="table-scroll">
              <table>{children}</table>
            </div>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          p: ({ children }) => <p>{withCitationChips(children, byIndex, onCitationClick)}</p>,
          li: ({ children }) => <li>{withCitationChips(children, byIndex, onCitationClick)}</li>,
          td: ({ children }) => <td>{withCitationChips(children, byIndex, onCitationClick)}</td>,
        }}
      >
        {content}
      </Markdown>
    </div>
  );
});

const CITATION_REFERENCE = /\[(\d{1,2})\]/g;

/** Walks rendered children and swaps `[n]` text for chips, leaving elements untouched. */
function withCitationChips(
  children: React.ReactNode,
  byIndex: Map<number, Citation>,
  onClick: (citation: Citation) => void,
): React.ReactNode {
  if (byIndex.size === 0) return children;

  const transform = (node: React.ReactNode, key: string): React.ReactNode => {
    if (typeof node === "string") {
      const parts: React.ReactNode[] = [];
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      CITATION_REFERENCE.lastIndex = 0;

      while ((match = CITATION_REFERENCE.exec(node)) !== null) {
        const citation = byIndex.get(Number(match[1]));
        if (!citation) continue;
        if (match.index > lastIndex) parts.push(node.slice(lastIndex, match.index));
        parts.push(
          <CitationChip
            key={`${key}-${match.index}`}
            citation={citation}
            onClick={() => onClick(citation)}
          />,
        );
        lastIndex = match.index + match[0].length;
      }
      if (parts.length === 0) return node;
      if (lastIndex < node.length) parts.push(node.slice(lastIndex));
      return parts;
    }
    if (Array.isArray(node)) {
      return node.map((child, index) => transform(child, `${key}-${index}`));
    }
    return node;
  };

  return transform(children, "c");
}

export function CitationChip({
  citation,
  onClick,
}: {
  citation: Citation;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={citation.label || citation.document}
      aria-label={`View source ${citation.index}: ${citation.label || citation.document}`}
      className={cn(
        "mx-0.5 inline-flex h-[1.1rem] min-w-[1.1rem] items-center justify-center rounded",
        "border border-accent/30 bg-accent-soft px-1 align-text-top",
        "tnum font-mono text-[10px] font-semibold text-accent",
        "hover:border-accent/60 hover:brightness-95",
      )}
    >
      {citation.index}
    </button>
  );
}

/** Compact list of sources beneath an answer, each opening the full passage. */
export function SourceList({
  citations,
  onCitationClick,
}: {
  citations: Citation[];
  onCitationClick: (citation: Citation) => void;
}) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-3 space-y-1.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
        Sources ({citations.length})
      </p>
      <ul className="space-y-1">
        {citations.map((citation) => (
          <li key={`${citation.index}-${citation.chunk_uid}`}>
            <button
              type="button"
              onClick={() => onCitationClick(citation)}
              className="group flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-surface-2"
            >
              <span className="tnum mt-0.5 shrink-0 font-mono text-[10px] font-semibold text-accent">
                [{citation.index}]
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-ink group-hover:text-accent">
                  {citation.label || citation.document}
                </span>
              </span>
              <ExternalLink
                className="mt-0.5 size-3.5 shrink-0 text-ink-3 group-hover:text-accent"
                aria-hidden
              />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Right-hand panel showing one retrieved passage in full.
 *
 * This is the verification surface: document, version, effective date, section, page (when
 * the format has pages), retrieval and rerank scores, and the exact text the model was given
 * — not a paraphrase of it.
 */
export function SourcePanel({
  citation,
  onClose,
}: {
  citation: Citation | null;
  onClose: () => void;
}) {
  if (!citation) return null;

  return (
    <aside
      aria-label={`Source ${citation.index}`}
      className="flex w-full flex-col border-border bg-surface lg:w-96 lg:shrink-0 lg:border-l"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
            Source [{citation.index}]
          </p>
          <h2 className="mt-0.5 text-[13px] font-semibold leading-snug text-ink">
            {citation.document_title || citation.document}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close source panel"
          className="rounded p-1 text-ink-3 hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3.5">
        <dl className="space-y-2 text-[13px]">
          {citation.version && <Meta label="Version" value={`v${citation.version}`} />}
          {citation.effective_date && (
            <Meta label="Effective date" value={citation.effective_date} />
          )}
          {citation.section && <Meta label="Section" value={citation.section} />}
          {citation.subsection && <Meta label="Subsection" value={citation.subsection} />}
          {/* Page is null for markdown sources — the system never invents one. */}
          <Meta
            label="Page"
            value={citation.page ? String(citation.page) : "not applicable (no pages in source format)"}
          />
          <Meta label="File" value={citation.document} mono />
          <Meta label="Chunk id" value={citation.chunk_uid} mono />
        </dl>

        <div className="mt-3 flex flex-wrap gap-2">
          {citation.retrieval_score !== null && citation.retrieval_score !== undefined && (
            <Badge tone="neutral">retrieval {formatMetric(citation.retrieval_score, 4)}</Badge>
          )}
          {citation.rerank_score !== null && citation.rerank_score !== undefined && (
            <Badge tone="accent">rerank {formatMetric(citation.rerank_score, 3)}</Badge>
          )}
        </div>

        <div className="mt-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
            Retrieved passage
          </p>
          <pre className="mt-1.5 whitespace-pre-wrap rounded-lg border border-border bg-surface-2 p-3 font-sans text-[13px] leading-relaxed text-ink">
            {citation.chunk}
          </pre>
          <p className="mt-2 text-[11px] text-ink-3">
            This is the exact text supplied to the model, not a reconstruction.
          </p>
        </div>
      </div>

      {citation.document_id && (
        <div className="border-t border-border p-3">
          <Link to={`/documents/${citation.document_id}`}>
            <Button size="sm" variant="secondary" icon={<FileText className="size-4" aria-hidden />} className="w-full">
              Open document
            </Button>
          </Link>
        </div>
      )}
    </aside>
  );
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-ink-3">{label}</dt>
      <dd className={cn("min-w-0 flex-1 break-words text-ink", mono && "font-mono text-[11px]")}>
        {value}
      </dd>
    </div>
  );
}
