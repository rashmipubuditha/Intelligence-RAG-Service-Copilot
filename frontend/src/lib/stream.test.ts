/**
 * SSE parser tests.
 *
 * The parser is the riskiest code in the frontend: it reassembles frames from arbitrary
 * network chunk boundaries, and a bug here either loses tokens or drops the citations event —
 * which would silently break the product's core promise. These tests feed deliberately
 * awkward chunk splits.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { streamChat } from "./stream";

/** Builds a fetch mock whose body streams the given string pieces verbatim. */
function mockFetchStream(pieces: string[], ok = true, status = 200) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
  return vi.fn().mockResolvedValue({
    ok,
    status,
    body,
    headers: new Headers({ "content-type": "text/event-stream" }),
    json: async () => ({}),
  } as unknown as Response);
}

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("streamChat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dispatches events in order and accumulates tokens", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchStream([
        frame("conversation", { conversation_id: "conv_1" }),
        frame("meta", { model: "test-model", request_id: "req_1" }),
        frame("retrieval", {
          rewritten_question: null,
          n_retrieved: 2,
          retrieval_ms: 70,
          rerank_ms: 500,
          sources: [],
        }),
        frame("token", { text: "Payslips " }),
        frame("token", { text: "are required " }),
        frame("token", { text: "[1]." }),
        frame("citations", { citations: [{ index: 1, document: "02_sow.md", chunk: "…" }] }),
        frame("evidence", { band: "strong", basis: "", disclaimer: "" }),
        frame("done", { result: { answer: "Payslips are required [1].", citations: [] } }),
      ]),
    );

    const seen: string[] = [];
    let text = "";
    let conversationId: string | null = null;
    let citationCount = -1;

    await streamChat(
      { question: "What documents?" },
      {
        onConversation: (id) => {
          seen.push("conversation");
          conversationId = id;
        },
        onMeta: () => seen.push("meta"),
        onRetrieval: () => seen.push("retrieval"),
        onToken: (piece) => {
          text += piece;
        },
        onCitations: (citations) => {
          seen.push("citations");
          citationCount = citations.length;
        },
        onEvidence: () => seen.push("evidence"),
        onDone: () => seen.push("done"),
        onError: () => seen.push("error"),
      },
    );

    expect(seen).toEqual(["conversation", "meta", "retrieval", "citations", "evidence", "done"]);
    expect(text).toBe("Payslips are required [1].");
    expect(conversationId).toBe("conv_1");
    expect(citationCount).toBe(1);
  });

  it("reassembles frames split across arbitrary chunk boundaries", async () => {
    // One frame delivered in three pieces, including a split inside the JSON payload.
    vi.stubGlobal(
      "fetch",
      mockFetchStream(['event: tok', 'en\ndata: {"text":"hel', 'lo"}\n\n']),
    );

    let text = "";
    await streamChat({ question: "q" }, { onToken: (piece) => (text += piece) });
    expect(text).toBe("hello");
  });

  it("handles several frames arriving in one chunk", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchStream([frame("token", { text: "a" }) + frame("token", { text: "b" })]),
    );

    let text = "";
    await streamChat({ question: "q" }, { onToken: (piece) => (text += piece) });
    expect(text).toBe("ab");
  });

  it("ignores a malformed frame without killing the stream", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchStream([
        "event: token\ndata: {not json}\n\n",
        frame("token", { text: "survived" }),
      ]),
    );

    let text = "";
    const onError = vi.fn();
    await streamChat({ question: "q" }, { onToken: (piece) => (text += piece), onError });
    expect(text).toBe("survived");
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a server error event through onError", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchStream([frame("error", { code: "llm_unavailable", message: "provider down" })]),
    );

    const onError = vi.fn();
    await streamChat({ question: "q" }, { onError });
    expect(onError).toHaveBeenCalledWith({ code: "llm_unavailable", message: "provider down" });
  });

  it("surfaces a pre-stream HTTP failure from the error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        body: null,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          error: { code: "index_not_ready", message: "No documents are indexed yet." },
        }),
      } as unknown as Response),
    );

    const onError = vi.fn();
    await streamChat({ question: "q" }, { onError });
    expect(onError).toHaveBeenCalledWith({
      code: "index_not_ready",
      message: "No documents are indexed yet.",
    });
  });

  it("treats an abort as a normal end, not an error", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));

    const onError = vi.fn();
    await streamChat({ question: "q" }, { onError });
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports an unreachable API as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const onError = vi.fn();
    await streamChat({ question: "q" }, { onError });
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ code: "network_error" }),
    );
  });
});
