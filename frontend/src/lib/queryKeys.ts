/**
 * Centralised TanStack Query keys.
 *
 * Kept in one place so invalidation after a mutation is exact: uploading a document must
 * invalidate the document list, the stats, and nothing else.
 */

export const queryKeys = {
  readiness: ["readiness"] as const,
  stats: ["stats"] as const,
  settings: ["settings"] as const,

  documents: (filters: Record<string, unknown> = {}) => ["documents", filters] as const,
  document: (id: string) => ["document", id] as const,
  documentChunks: (id: string, page: number) => ["document", id, "chunks", page] as const,

  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,

  evaluationDatasets: ["evaluation", "datasets"] as const,
  evaluationRuns: ["evaluation", "runs"] as const,
  evaluationRun: (id: string) => ["evaluation", "run", id] as const,
};

/** Document/eval work happens in the background, so these views poll while work is pending. */
export const POLL_INTERVAL_MS = 2000;
