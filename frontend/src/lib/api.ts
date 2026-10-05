/**
 * Typed API client.
 *
 * Every type here is derived from `src/types/api.d.ts`, which is generated from the
 * backend's own OpenAPI schema (`npm run gen:api`). That is the point: a field renamed in
 * a Pydantic model becomes a TypeScript compile error here rather than a runtime
 * `undefined` three screens deep in the UI.
 *
 * The client always talks to a relative `/api`, so no base URL is configured anywhere —
 * Vite proxies it in dev, nginx serves it in production.
 */

import type { components } from "../types/api";

// --- schema-derived aliases -------------------------------------------------

export type Citation = components["schemas"]["Citation"];
export type Evidence = components["schemas"]["Evidence"];
export type EvidenceBand = Evidence["band"];
export type Conflict = components["schemas"]["Conflict"];
export type StageTimings = components["schemas"]["StageTimings"];
export type TokenUsage = components["schemas"]["TokenUsage"];

export type ChatRequest = components["schemas"]["ChatRequest"];
export type ChatResponse = components["schemas"]["ChatResponse"];

export type DocumentRecord = components["schemas"]["DocumentResponse"];
export type DocumentStatus = DocumentRecord["status"];
export type DocumentDetail = components["schemas"]["DocumentDetailResponse"];
export type DocumentList = components["schemas"]["DocumentListResponse"];
export type ChunkRecord = components["schemas"]["ChunkResponse"];
export type ChunkList = components["schemas"]["ChunkListResponse"];
export type UploadResponse = components["schemas"]["UploadResponse"];
export type SectionNode = components["schemas"]["SectionNode"];

export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type ConversationList = components["schemas"]["ConversationListResponse"];
export type ConversationDetail = components["schemas"]["ConversationDetailResponse"];
export type MessageRecord = components["schemas"]["MessageResponse"];

export type EvaluationRunSummary = components["schemas"]["EvaluationRunSummary"];
export type EvaluationRunDetail = components["schemas"]["EvaluationRunDetail"];
export type EvaluationRunRequest = components["schemas"]["EvaluationRunRequest"];

export type SettingsResponse = components["schemas"]["SettingsResponse"];
export type SettingsPatchRequest = components["schemas"]["SettingsPatchRequest"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];

export type StatsResponse = components["schemas"]["StatsResponse"];
export type ActivityEntry = components["schemas"]["ActivityEntry"];

/** The backend's uniform error envelope — every non-2xx response has this shape. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string | null;
    timestamp?: string;
  };
}

/**
 * An API failure carrying the backend's stable error code and request id.
 *
 * The request id is surfaced in the UI so a user can quote it in a bug report and it can be
 * grepped straight out of the server logs.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string | null;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody["error"]>, fallback: string) {
    super(body.message || fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || "unknown_error";
    this.requestId = body.request_id ?? null;
    this.details = body.details;
  }

  /** True when retrying the identical request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status >= 500 || this.status === 429;
  }
}

// --- core request handling --------------------------------------------------

const API_KEY_STORAGE = "cic.apiKey";

export function getApiKey(): string | null {
  try {
    return localStorage.getItem(API_KEY_STORAGE);
  } catch {
    return null; // private browsing / storage disabled
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    /* non-fatal: the request simply goes out unauthenticated */
  }
}

export function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...authHeaders(),
        ...(init.headers || {}),
      },
    });
  } catch {
    // Network-level failure: fetch rejects without a status, so there is nothing to attach.
    throw new ApiError(0, { code: "network_error" }, "Could not reach the API. Is the backend running?");
  }

  if (response.status === 204) return undefined as T;

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const body = (payload as ApiErrorBody | null)?.error ?? {};
    throw new ApiError(response.status, body, `Request failed with status ${response.status}`);
  }
  return payload as T;
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

// --- endpoints --------------------------------------------------------------

export const api = {
  // system
  readiness: () => request<ReadinessResponse>("/api/health/ready"),
  stats: () => request<StatsResponse>("/api/stats"),
  settings: () => request<SettingsResponse>("/api/settings"),
  updateSettings: (body: SettingsPatchRequest) =>
    request<SettingsResponse>("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // chat (non-streaming; the streaming path lives in lib/stream.ts)
  chat: (body: ChatRequest) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // conversations
  conversations: (params: { limit?: number; offset?: number } = {}) =>
    request<ConversationList>(`/api/conversations${query(params)}`),
  conversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  // documents
  documents: (
    params: { status?: string; doc_type?: string; q?: string; limit?: number; offset?: number } = {},
  ) => request<DocumentList>(`/api/documents${query(params)}`),
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  documentChunks: (id: string, params: { limit?: number; offset?: number } = {}) =>
    request<ChunkList>(`/api/documents/${id}/chunks${query(params)}`),
  documentDownloadUrl: (id: string) => `/api/documents/${id}/download`,

  uploadDocuments: (files: File[], options: { replace?: boolean } = {}) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    // Content-Type is deliberately omitted: the browser must set the multipart boundary.
    return request<UploadResponse>(`/api/documents${query({ replace: options.replace })}`, {
      method: "POST",
      body: form,
    });
  },

  patchDocument: (id: string, body: components["schemas"]["DocumentPatchRequest"]) =>
    request<DocumentRecord>(`/api/documents/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  reindexDocument: (id: string) =>
    request<components["schemas"]["UploadedDocument"]>(`/api/documents/${id}/reindex`, {
      method: "POST",
    }),
  deleteDocument: (id: string, purgeOriginal = false) =>
    request<void>(`/api/documents/${id}${query({ purge_original: purgeOriginal })}`, {
      method: "DELETE",
    }),

  // evaluation
  evaluationDatasets: () =>
    request<
      Array<{
        name: string;
        n_questions?: number;
        categories?: Record<string, number>;
        refusal_cases?: number;
        error?: string;
      }>
    >("/api/evaluation/datasets"),
  evaluationRuns: (limit = 25) =>
    request<EvaluationRunSummary[]>(`/api/evaluation/runs${query({ limit })}`),
  evaluationRun: (id: string) => request<EvaluationRunDetail>(`/api/evaluation/runs/${id}`),
  startEvaluation: (body: EvaluationRunRequest) =>
    request<EvaluationRunSummary | { status: string; message: string; poll: string }>(
      "/api/evaluation/runs",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
};
