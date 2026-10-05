/**
 * Documents page: upload, list, filter, re-index, activate/deactivate, delete.
 *
 * The list polls only while a document is `processing`, so an idle page makes no requests.
 */

import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  FileText,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { ApiError, api, type DocumentRecord } from "../lib/api";
import { POLL_INTERVAL_MS, queryKeys } from "../lib/queryKeys";
import { formatBytes, formatDate, formatRelative } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Notice,
  Skeleton,
  inputClass,
} from "../components/ui";
import { StatusPill } from "../components/domain";

const ACCEPTED = ".md,.txt,.pdf,.docx";

export default function DocumentsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [pendingDelete, setPendingDelete] = useState<DocumentRecord | null>(null);
  const [uploadErrors, setUploadErrors] = useState<Array<{ file: string; error: string }>>([]);
  const [uploadNotes, setUploadNotes] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const filters = { q: search || undefined, status: statusFilter || undefined };

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.documents(filters),
    queryFn: () => api.documents({ ...filters, limit: 100 }),
    // Poll only while something is actually being indexed.
    refetchInterval: (query) =>
      query.state.data?.documents.some((document) => document.status === "processing")
        ? POLL_INTERVAL_MS
        : false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: queryKeys.stats });
    queryClient.invalidateQueries({ queryKey: queryKeys.readiness });
  };

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadDocuments(files),
    onSuccess: (result) => {
      setUploadErrors(result.failed ?? []);
      const duplicates = (result.uploaded ?? [])
        .filter((item) => item.duplicate_of)
        .map((item) => `${item.document.filename} was already indexed — no duplicate created.`);
      const indexed = (result.uploaded ?? [])
        .filter((item) => !item.duplicate_of)
        .map((item) => `${item.document.title} indexed into ${item.chunks} chunks.`);
      setUploadNotes([...indexed, ...duplicates]);
      invalidate();
    },
    onError: (cause) => {
      // The backend puts per-file failures in `details.failures` when nothing could be indexed.
      const failures =
        cause instanceof ApiError
          ? (cause.details?.failures as Array<{ file: string; error: string }> | undefined)
          : undefined;
      setUploadErrors(
        Array.isArray(failures)
          ? failures
          : [{ file: "upload", error: cause instanceof Error ? cause.message : "Upload failed" }],
      );
      setUploadNotes([]);
    },
  });

  const reindex = useMutation({
    mutationFn: (id: string) => api.reindexDocument(id),
    onSuccess: invalidate,
  });

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "indexed" | "inactive" }) =>
      api.patchDocument(id, { status }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteDocument(id, true),
    onSuccess: () => {
      setPendingDelete(null);
      invalidate();
    },
  });

  const handleFiles = (files: FileList | null) => {
    if (!files?.length) return;
    setUploadErrors([]);
    setUploadNotes([]);
    upload.mutate(Array.from(files));
  };

  const documents = data?.documents ?? [];

  return (
    <div className="space-y-4 p-5">
      {/* Upload */}
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        className={`rounded-card border-2 border-dashed px-5 py-7 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-border bg-surface"
        }`}
      >
        <Upload className="mx-auto size-6 text-ink-3" aria-hidden />
        <p className="mt-2 text-[13px] font-medium text-ink">
          Drop compliance documents here, or
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="ml-1 text-accent underline"
          >
            browse
          </button>
        </p>
        <p className="mt-1 text-[11px] text-ink-3">
          Markdown, plain text, PDF or DOCX · up to 20 MB each · validated by content, not just
          by extension
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          className="sr-only"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = ""; // allow re-selecting the same file
          }}
        />
        {upload.isPending && (
          <p className="mt-3 text-[13px] text-accent" role="status">
            Extracting, chunking, embedding and indexing…
          </p>
        )}
      </div>

      {uploadNotes.length > 0 && (
        <Notice tone="ok" title="Upload complete">
          <ul className="space-y-0.5">
            {uploadNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Notice>
      )}

      {uploadErrors.length > 0 && (
        <Notice tone="danger" title={`${uploadErrors.length} file(s) rejected`}>
          <ul className="space-y-0.5">
            {uploadErrors.map((failure, index) => (
              <li key={index}>
                <span className="font-medium">{failure.file}</span>: {failure.error}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <label htmlFor="doc-search" className="sr-only">
            Search documents
          </label>
          <input
            id="doc-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search title or filename…"
            className={`${inputClass} pl-9`}
          />
        </div>
        <label htmlFor="doc-status" className="sr-only">
          Filter by status
        </label>
        <select
          id="doc-status"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className={`${inputClass} w-auto`}
        >
          <option value="">All statuses</option>
          <option value="indexed">Indexed</option>
          <option value="inactive">Inactive</option>
          <option value="processing">Processing</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-10" />
            ))}
          </div>
        ) : error ? (
          <ErrorState
            message={error instanceof Error ? error.message : "Could not load documents."}
            code={error instanceof ApiError ? error.code : undefined}
            requestId={error instanceof ApiError ? error.requestId : undefined}
            onRetry={() => void refetch()}
          />
        ) : documents.length === 0 ? (
          <EmptyState
            icon={<FileText className="size-7" aria-hidden />}
            title={search || statusFilter ? "No documents match these filters" : "No documents indexed"}
            description={
              search || statusFilter
                ? "Clear the filters to see the full corpus."
                : "Upload a policy document above to make it searchable."
            }
            action={
              (search || statusFilter) && (
                <Button
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setStatusFilter("");
                  }}
                >
                  Clear filters
                </Button>
              )
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <caption className="sr-only">Indexed compliance documents</caption>
              <thead>
                <tr className="border-b border-border bg-surface-2 text-left text-ink-3">
                  <th scope="col" className="px-4 py-2.5 font-medium">Document</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Type</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Version</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Effective</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Chunks</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Uploaded</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                    <td className="max-w-xs px-4 py-2.5">
                      <Link
                        to={`/documents/${document.id}`}
                        className="block truncate font-medium text-ink hover:text-accent hover:underline"
                      >
                        {document.title}
                      </Link>
                      <span className="block truncate font-mono text-[11px] text-ink-3">
                        {document.filename} · {formatBytes(document.byte_size)}
                      </span>
                      {document.injection_flags?.length ? (
                        <Badge tone="caution" className="mt-1 text-[10px]">
                          <AlertTriangle className="size-3" aria-hidden />
                          {document.injection_flags.length} flagged
                        </Badge>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-ink-2">{document.doc_type}</td>
                    <td className="tnum px-4 py-2.5 text-ink-2">
                      {document.version ? `v${document.version}` : "–"}
                    </td>
                    <td className="tnum px-4 py-2.5 text-ink-2">
                      {formatDate(document.effective_date)}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-ink-2">{document.chunk_count}</td>
                    <td className="px-4 py-2.5">
                      <StatusPill status={document.status} />
                      {document.failure_reason && (
                        <span className="mt-1 block max-w-48 truncate text-[11px] text-danger" title={document.failure_reason}>
                          {document.failure_reason}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-ink-3">{formatRelative(document.uploaded_at)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <IconButton
                          label={document.status === "inactive" ? "Activate" : "Deactivate"}
                          onClick={() =>
                            setStatus.mutate({
                              id: document.id,
                              status: document.status === "inactive" ? "indexed" : "inactive",
                            })
                          }
                          disabled={document.status === "failed" || setStatus.isPending}
                        >
                          {document.status === "inactive" ? (
                            <Eye className="size-4" aria-hidden />
                          ) : (
                            <EyeOff className="size-4" aria-hidden />
                          )}
                        </IconButton>
                        <IconButton
                          label="Re-index"
                          onClick={() => reindex.mutate(document.id)}
                          disabled={reindex.isPending || document.status === "processing"}
                        >
                          <RefreshCw
                            className={`size-4 ${reindex.isPending && reindex.variables === document.id ? "animate-spin" : ""}`}
                            aria-hidden
                          />
                        </IconButton>
                        <IconButton label="Delete" danger onClick={() => setPendingDelete(document)}>
                          <Trash2 className="size-4" aria-hidden />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data?.page && documents.length > 0 && (
        <p className="text-[11px] text-ink-3">
          Showing {data.page.returned} of {data.page.total} documents.
        </p>
      )}

      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="Delete this document?"
        description={pendingDelete?.title}
        footer={
          <>
            <Button size="sm" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={remove.isPending}
              onClick={() => pendingDelete && remove.mutate(pendingDelete.id)}
            >
              Delete permanently
            </Button>
          </>
        }
      >
        <p>
          Its {pendingDelete?.chunk_count ?? 0} chunks will be removed from both the vector index
          and the keyword index, and the stored original will be purged.
        </p>
        <p className="mt-2">
          Past answers that cited this document keep their recorded passage in the audit log —
          deleting a document never rewrites history.
        </p>
        <p className="mt-2">
          To stop a document being retrieved without deleting it, deactivate it instead.
        </p>
      </Dialog>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
        danger ? "text-ink-3 hover:bg-danger-soft hover:text-danger" : "text-ink-3 hover:bg-surface hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}
