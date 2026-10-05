/**
 * Document detail: metadata, section tree, and the indexed chunks themselves.
 *
 * Showing the actual chunks matters. "Why didn't it find that rule?" is almost always
 * answered by looking at how the document was split, and this page is where that is visible
 * rather than guessed at.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileText, RefreshCw } from "lucide-react";
import { ApiError, api } from "../lib/api";
import { POLL_INTERVAL_MS, queryKeys } from "../lib/queryKeys";
import { formatBytes, formatDate, formatDateTime } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Skeleton,
  Tabs,
} from "../components/ui";
import { InjectionFlags, StatusPill } from "../components/domain";

const PAGE_SIZE = 25;
type TabId = "sections" | "chunks" | "metadata";

export default function DocumentDetailPage() {
  const { documentId = "" } = useParams();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabId>("sections");
  const [page, setPage] = useState(0);

  const {
    data: detail,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.document(documentId),
    queryFn: () => api.document(documentId),
    enabled: Boolean(documentId),
    refetchInterval: (query) =>
      query.state.data?.document.status === "processing" ? POLL_INTERVAL_MS : false,
  });

  const { data: chunks, isFetching: chunksFetching } = useQuery({
    queryKey: queryKeys.documentChunks(documentId, page),
    queryFn: () => api.documentChunks(documentId, { limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    enabled: Boolean(documentId) && tab === "chunks",
  });

  const reindex = useMutation({
    mutationFn: () => api.reindexDocument(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.stats });
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <ErrorState
        title="Document not found"
        message={error instanceof Error ? error.message : "This document does not exist."}
        code={error instanceof ApiError ? error.code : undefined}
        requestId={error instanceof ApiError ? error.requestId : undefined}
        onRetry={() => void refetch()}
      />
    );
  }

  const document = detail.document;

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to="/documents"
            className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            All documents
          </Link>
          <h1 className="mt-1 truncate text-base font-semibold text-ink">{document.title}</h1>
          <p className="truncate font-mono text-[11px] text-ink-3">{document.filename}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusPill status={document.status} />
          <a href={api.documentDownloadUrl(document.id)} download>
            <Button size="sm" icon={<Download className="size-4" aria-hidden />}>
              Original
            </Button>
          </a>
          <Button
            size="sm"
            loading={reindex.isPending}
            onClick={() => reindex.mutate()}
            icon={<RefreshCw className="size-4" aria-hidden />}
          >
            Re-index
          </Button>
        </div>
      </div>

      {document.failure_reason && (
        <ErrorState
          title="Indexing failed"
          message={document.failure_reason}
          onRetry={() => reindex.mutate()}
        />
      )}

      {document.injection_flags?.length ? (
        <InjectionFlags flags={document.injection_flags} />
      ) : null}

      {/* Metadata summary */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Summary label="Version" value={document.version ? `v${document.version}` : "not stated"} />
        <Summary label="Effective date" value={formatDate(document.effective_date)} />
        <Summary label="Document type" value={document.doc_type} />
        <Summary label="Indexed chunks" value={String(document.chunk_count)} />
      </div>

      <Card>
        <div className="px-5 pt-3">
          <Tabs
            tabs={[
              { id: "sections", label: "Sections", count: detail.sections.length },
              { id: "chunks", label: "Indexed chunks", count: document.chunk_count },
              { id: "metadata", label: "Metadata" },
            ] as const}
            active={tab}
            onChange={(id) => setTab(id as TabId)}
          />
        </div>

        {tab === "sections" && (
          <div className="p-5">
            {detail.sections.length === 0 ? (
              <EmptyState
                icon={<FileText className="size-6" aria-hidden />}
                title="No sections detected"
                description="This document has no heading structure, so it was chunked on paragraph boundaries."
              />
            ) : (
              <ul className="space-y-2">
                {detail.sections.map((section) => (
                  <li
                    key={section.section}
                    className="rounded-lg border border-border bg-surface-2 px-3.5 py-2.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[13px] font-medium text-ink">{section.section}</p>
                      <span className="tnum text-[11px] text-ink-3">
                        {section.chunk_count} chunk{section.chunk_count === 1 ? "" : "s"}
                        {section.pages?.length ? ` · p. ${section.pages.join(", ")}` : ""}
                      </span>
                    </div>
                    {section.subsections.length > 0 && (
                      <ul className="mt-1.5 flex flex-wrap gap-1.5">
                        {section.subsections.map((subsection) => (
                          <li key={subsection}>
                            <Badge tone="neutral" className="text-[10px]">
                              §{subsection}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-[11px] text-ink-3">
              Subsections become their own retrievable chunks, so a citation can name §3.1 rather
              than only §3.
            </p>
          </div>
        )}

        {tab === "chunks" && (
          <div className="p-5">
            {chunksFetching && !chunks ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-20" />
                ))}
              </div>
            ) : !chunks?.chunks.length ? (
              <EmptyState title="No chunks" description="This document produced no indexed chunks." />
            ) : (
              <>
                <ul className="space-y-3">
                  {chunks.chunks.map((chunk) => (
                    <li key={chunk.chunk_uid} className="rounded-lg border border-border">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-2 px-3.5 py-2">
                        <p className="text-[13px] font-medium text-ink">{chunk.label}</p>
                        <span className="tnum font-mono text-[10px] text-ink-3">
                          #{chunk.chunk_index} · {chunk.token_estimate} tok ·{" "}
                          {chunk.chunk_uid.slice(0, 8)}
                        </span>
                      </div>
                      <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap px-3.5 py-2.5 font-sans text-[13px] leading-relaxed text-ink-2">
                        {chunk.text}
                      </pre>
                    </li>
                  ))}
                </ul>

                {chunks.page.total > PAGE_SIZE && (
                  <div className="mt-4 flex items-center justify-between">
                    <Button
                      size="sm"
                      disabled={page === 0}
                      onClick={() => setPage((value) => Math.max(0, value - 1))}
                    >
                      Previous
                    </Button>
                    <span className="tnum text-[11px] text-ink-3">
                      {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, chunks.page.total)} of{" "}
                      {chunks.page.total}
                    </span>
                    <Button
                      size="sm"
                      disabled={(page + 1) * PAGE_SIZE >= chunks.page.total}
                      onClick={() => setPage((value) => value + 1)}
                    >
                      Next
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {tab === "metadata" && (
          <dl className="divide-y divide-border">
            <MetaRow label="Document id" value={document.id} mono />
            <MetaRow label="Title" value={document.title} />
            <MetaRow label="Filename" value={document.filename} mono />
            <MetaRow label="Type" value={document.doc_type} />
            <MetaRow label="Version" value={document.version ?? "not stated in document"} />
            <MetaRow label="Effective date" value={formatDate(document.effective_date)} />
            <MetaRow label="Publication date" value={formatDate(document.publication_date)} />
            <MetaRow label="Owner" value={document.owner ?? "not stated"} />
            <MetaRow label="Review cycle" value={document.review_cycle ?? "not stated"} />
            <MetaRow label="MIME type" value={document.mime_type} mono />
            <MetaRow label="Size" value={formatBytes(document.byte_size)} />
            <MetaRow
              label="Pages"
              value={
                document.page_count
                  ? String(document.page_count)
                  : "not applicable (source format has no pages)"
              }
            />
            <MetaRow label="Embedding model" value={document.embedding_model ?? "–"} mono />
            <MetaRow label="Content hash" value={document.content_sha256} mono />
            <MetaRow label="Uploaded" value={formatDateTime(document.uploaded_at)} />
            <MetaRow label="Indexed" value={formatDateTime(document.indexed_at)} />
          </dl>
        )}
      </Card>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <p className="text-[11px] font-medium text-ink-3">{label}</p>
      <p className="mt-0.5 truncate text-[13px] font-medium text-ink">{value}</p>
    </div>
  );
}

function MetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-4 px-5 py-2.5 text-[13px]">
      <dt className="w-40 shrink-0 text-ink-3">{label}</dt>
      <dd className={mono ? "min-w-0 break-all font-mono text-[11px] text-ink" : "min-w-0 text-ink"}>
        {value}
      </dd>
    </div>
  );
}
