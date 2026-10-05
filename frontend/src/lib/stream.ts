/**
 * SSE client for POST /api/chat/stream.
 *
 * `EventSource` is not usable here: the chat endpoint is a POST with a JSON body and an
 * auth header, and EventSource supports neither. So the stream is read with fetch +
 * ReadableStream and the SSE wire format is parsed by hand — which is about 30 lines and
 * gives us cancellation via AbortController for free.
 *
 * Event order from the backend is fixed:
 *   conversation → meta → retrieval → token* → citations → evidence → [conflicts] → done
 * An `error` event replaces whatever would have followed.
 */

import { authHeaders, type Citation, type Conflict, type Evidence, type StageTimings, type TokenUsage } from "./api";

export interface RetrievalEventSource {
  chunk_uid: string;
  label: string;
  document_id: string;
  score: number;
}

export interface StreamHandlers {
  onConversation?: (conversationId: string) => void;
  onMeta?: (meta: { model: string; request_id: string | null }) => void;
  onRetrieval?: (payload: {
    rewritten_question: string | null;
    n_retrieved: number;
    retrieval_ms: number;
    rerank_ms: number;
    sources: RetrievalEventSource[];
  }) => void;
  /** Called for every text delta. Already stripped of citation markers by the server. */
  onToken?: (text: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onEvidence?: (evidence: Evidence) => void;
  onConflicts?: (conflicts: Conflict[]) => void;
  onDone?: (result: {
    answer: string;
    citations: Citation[];
    evidence: Evidence;
    conflicts: Conflict[];
    refused: boolean;
    model: string;
    timings: StageTimings;
    token_usage: TokenUsage;
    conversation_id?: string;
  }) => void;
  onError?: (error: { code: string; message: string }) => void;
}

export interface StreamChatOptions {
  question: string;
  conversationId?: string | null;
  k?: number | null;
  signal?: AbortSignal;
}

/**
 * Open the stream and dispatch events to handlers. Resolves when the stream closes.
 *
 * Aborting via `options.signal` resolves normally rather than throwing: a user pressing
 * Stop is not an error, and whatever was already streamed stays on screen (the server
 * persists and audits the partial result on its side).
 */
export async function streamChat(
  options: StreamChatOptions,
  handlers: StreamHandlers,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        question: options.question,
        conversation_id: options.conversationId ?? null,
        k: options.k ?? null,
      }),
      signal: options.signal,
    });
  } catch (cause) {
    if (isAbort(cause)) return;
    handlers.onError?.({
      code: "network_error",
      message: "Could not reach the API. Is the backend running?",
    });
    return;
  }

  // A pre-stream failure (401, 429, 503) arrives as a normal JSON error envelope.
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    handlers.onError?.({
      code: body?.error?.code ?? "http_error",
      message: body?.error?.message ?? `Request failed with status ${response.status}`,
    });
    return;
  }
  if (!response.body) {
    handlers.onError?.({ code: "no_stream", message: "The server returned no stream body." });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. A partial frame stays in the buffer.
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        dispatch(buffer.slice(0, boundary), handlers);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) dispatch(buffer, handlers);
  } catch (cause) {
    if (!isAbort(cause)) {
      handlers.onError?.({
        code: "stream_failed",
        message: cause instanceof Error ? cause.message : "The stream ended unexpectedly.",
      });
    }
  } finally {
    reader.releaseLock();
  }
}

function dispatch(frame: string, handlers: StreamHandlers): void {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return;

  // Untrusted wire JSON. Typed as `any` deliberately: each branch below reads only the
  // fields its handler declares, and the backend's event contract is fixed and tested.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let payload: any;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return; // a malformed frame must not kill the stream
  }

  switch (eventName) {
    case "conversation":
      handlers.onConversation?.(payload.conversation_id);
      break;
    case "meta":
      handlers.onMeta?.(payload);
      break;
    case "retrieval":
      handlers.onRetrieval?.(payload);
      break;
    case "token":
      handlers.onToken?.(payload.text ?? "");
      break;
    case "citations":
      handlers.onCitations?.(payload.citations ?? []);
      break;
    case "evidence":
      handlers.onEvidence?.(payload);
      break;
    case "conflicts":
      handlers.onConflicts?.(payload.conflicts ?? []);
      break;
    case "done":
      handlers.onDone?.(payload.result ?? payload);
      break;
    case "error":
      handlers.onError?.({
        code: payload.code ?? "unknown_error",
        message: payload.message ?? "The request failed.",
      });
      break;
    default:
      break;
  }
}

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}
