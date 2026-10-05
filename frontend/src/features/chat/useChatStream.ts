/**
 * Chat state machine.
 *
 * Owns the transcript, the in-flight stream, and cancellation. Kept out of the component so
 * the reducer logic is testable without rendering, and so the component stays about layout.
 *
 * Streaming is the primary path: the user sees the first token in ~2 s regardless of how long
 * the full answer takes, and citations resolve server-side at the end of the stream.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Citation, Conflict, Evidence, StageTimings, TokenUsage } from "../../lib/api";
import { streamChat, type RetrievalEventSource } from "../../lib/stream";

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** True while tokens are still arriving for this turn. */
  streaming?: boolean;
  citations?: Citation[];
  evidence?: Evidence;
  conflicts?: Conflict[];
  refused?: boolean;
  model?: string;
  timings?: StageTimings;
  tokenUsage?: TokenUsage;
  retrieval?: {
    rewritten_question: string | null;
    n_retrieved: number;
    retrieval_ms: number;
    rerank_ms: number;
    sources: RetrievalEventSource[];
  };
  error?: { code: string; message: string };
}

let turnCounter = 0;
const nextId = () => `turn_${++turnCounter}`;

export function useChatStream(initialConversationId?: string | null) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId ?? null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const lastQuestionRef = useRef<string | null>(null);
  // Mirrored into state because the component renders a Retry affordance from it: reading
  // `lastQuestionRef.current` during render would not re-render when it changed.
  const [canRetry, setCanRetry] = useState(false);

  // Cancel any in-flight stream when the component unmounts, so navigating away does not
  // leave a dangling request writing into unmounted state.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const patchAssistant = useCallback((id: string, patch: Partial<ChatTurn>) => {
    setTurns((current) =>
      current.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)),
    );
  }, []);

  const send = useCallback(
    async (question: string, options: { k?: number | null } = {}) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      lastQuestionRef.current = trimmed;
      setCanRetry(true);
      const assistantId = nextId();

      setTurns((current) => [
        ...current,
        { id: nextId(), role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "", streaming: true },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      await streamChat(
        { question: trimmed, conversationId, k: options.k ?? null, signal: controller.signal },
        {
          onConversation: (id) => setConversationId(id),
          onMeta: (meta) => patchAssistant(assistantId, { model: meta.model }),
          onRetrieval: (payload) => patchAssistant(assistantId, { retrieval: payload }),
          onToken: (text) =>
            setTurns((current) =>
              current.map((turn) =>
                turn.id === assistantId ? { ...turn, content: turn.content + text } : turn,
              ),
            ),
          onCitations: (citations) => patchAssistant(assistantId, { citations }),
          onEvidence: (evidence) => patchAssistant(assistantId, { evidence }),
          onConflicts: (conflicts) => patchAssistant(assistantId, { conflicts }),
          onDone: (result) =>
            patchAssistant(assistantId, {
              streaming: false,
              // Trust the server's final answer text over the accumulated deltas.
              content: result.answer || "",
              citations: result.citations,
              evidence: result.evidence,
              conflicts: result.conflicts,
              refused: result.refused,
              model: result.model,
              timings: result.timings,
              tokenUsage: result.token_usage,
            }),
          onError: (error) => patchAssistant(assistantId, { streaming: false, error }),
        },
      );

      setIsStreaming(false);
      abortRef.current = null;
      // A stop or a transport failure can leave the turn marked streaming; clear it.
      patchAssistant(assistantId, { streaming: false });
    },
    [conversationId, isStreaming, patchAssistant],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const retryLast = useCallback(
    (options: { k?: number | null } = {}) => {
      const question = lastQuestionRef.current;
      if (!question) return;
      // Drop the failed exchange before retrying so the transcript does not accumulate
      // half-finished attempts.
      setTurns((current) => current.slice(0, -2));
      void send(question, options);
    },
    [send],
  );

  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setTurns([]);
    setConversationId(null);
    lastQuestionRef.current = null;
    setCanRetry(false);
  }, []);

  const loadTranscript = useCallback((loaded: ChatTurn[], id: string) => {
    setTurns(loaded);
    setConversationId(id);
  }, []);

  return {
    turns,
    conversationId,
    isStreaming,
    send,
    stop,
    retryLast,
    clear,
    loadTranscript,
    canRetry,
  };
}
