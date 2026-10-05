/**
 * Chat page.
 *
 * Layout: transcript on the left, source panel on the right. The composer is pinned, the
 * transcript auto-scrolls while streaming, and every assistant turn carries its evidence
 * band, conflicts, citations and timings — so the answer can be judged, not just read.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, History, MessagesSquare, Plus, RotateCcw, Square, Trash2 } from "lucide-react";
import { api, type Citation } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { cn, formatMs, formatRelative, formatTokens, truncate } from "../lib/format";
import { Badge, Button, EmptyState, ErrorState, Notice } from "../components/ui";
import { ConflictCallout, EvidenceBadge } from "../components/domain";
import { AnswerBody, SourceList, SourcePanel } from "../features/chat/Answer";
import { useChatStream, type ChatTurn } from "../features/chat/useChatStream";

const SUGGESTED_QUESTIONS = [
  "What are the KYC requirements for high-risk customers?",
  "What documents are required for customer due diligence?",
  "When is enhanced due diligence required?",
  "What are the escalation requirements for suspicious transactions?",
  "How often must sanctions screening be repeated for medium-risk clients?",
  "Is a passport that expired 4 months ago acceptable as primary ID?",
];

export default function ChatPage() {
  const { conversationId: routeConversationId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const chat = useChatStream(routeConversationId ?? null);
  const [draft, setDraft] = useState("");
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const { data: stats } = useQuery({ queryKey: queryKeys.stats, queryFn: api.stats });
  const { data: conversations } = useQuery({
    queryKey: queryKeys.conversations,
    queryFn: () => api.conversations({ limit: 25 }),
    enabled: showHistory,
  });

  const corpusEmpty = stats?.index?.chunks === 0;

  // Load a transcript when the route carries a conversation id (deep link / history click).
  const { data: loadedConversation, error: loadError } = useQuery({
    queryKey: queryKeys.conversation(routeConversationId ?? ""),
    queryFn: () => api.conversation(routeConversationId!),
    enabled: Boolean(routeConversationId),
  });

  useEffect(() => {
    if (!loadedConversation) return;
    const turns: ChatTurn[] = loadedConversation.messages.map((message, index) => ({
      id: `loaded_${index}`,
      role: message.role === "user" ? "user" : "assistant",
      content: message.content,
      citations: (message.citations ?? []) as Citation[],
      evidence: message.evidence as ChatTurn["evidence"],
      conflicts: (message.conflicts ?? []) as ChatTurn["conflicts"],
      refused: message.refused,
      model: message.model ?? undefined,
      timings: message.timings as ChatTurn["timings"],
      tokenUsage: message.token_usage as ChatTurn["tokenUsage"],
    }));
    chat.loadTranscript(turns, loadedConversation.id);
  }, [loadedConversation]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the newest content in view while tokens stream in.
  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [chat.turns]);

  const submit = (question: string) => {
    if (!question.trim() || chat.isStreaming) return;
    setDraft("");
    setActiveCitation(null);
    void chat.send(question).then(() => {
      // A new conversation gets its own URL so it can be shared and reloaded.
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      queryClient.invalidateQueries({ queryKey: queryKeys.stats });
    });
  };

  const startNew = () => {
    chat.clear();
    setActiveCitation(null);
    setDraft("");
    if (routeConversationId) navigate("/chat");
    composerRef.current?.focus();
  };

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] min-w-0 lg:h-[calc(100dvh-3.5rem)]">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-between gap-2 border-b border-border bg-surface px-4 py-2">
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" icon={<Plus className="size-4" aria-hidden />} onClick={startNew}>
              New
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<History className="size-4" aria-hidden />}
              onClick={() => setShowHistory((value) => !value)}
              aria-expanded={showHistory}
            >
              History
            </Button>
          </div>
          {chat.turns.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Trash2 className="size-4" aria-hidden />}
              onClick={startNew}
            >
              Clear
            </Button>
          )}
        </div>

        {showHistory && (
          <div className="max-h-56 overflow-y-auto border-b border-border bg-surface-2 px-4 py-2">
            {!conversations?.conversations.length ? (
              <p className="py-3 text-center text-[13px] text-ink-3">No previous conversations.</p>
            ) : (
              <ul className="space-y-0.5">
                {conversations.conversations.map((conversation) => (
                  <li key={conversation.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setShowHistory(false);
                        navigate(`/chat/${conversation.id}`);
                      }}
                      className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-surface"
                    >
                      <span className="min-w-0 truncate text-[13px] text-ink">
                        {truncate(conversation.title, 70)}
                      </span>
                      <span className="shrink-0 text-[11px] text-ink-3">
                        {conversation.message_count} msg · {formatRelative(conversation.updated_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Transcript */}
        <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 py-5">
            {loadError ? (
              <ErrorState
                title="Conversation could not be loaded"
                message={loadError instanceof Error ? loadError.message : "Unknown error"}
                onRetry={() => navigate("/chat")}
              />
            ) : corpusEmpty ? (
              <EmptyState
                icon={<MessagesSquare className="size-7" aria-hidden />}
                title="No documents are indexed yet"
                description="Upload a compliance document before asking questions — answers are only ever drawn from the indexed corpus."
                action={
                  <Button variant="primary" size="sm" onClick={() => navigate("/documents")}>
                    Go to Documents
                  </Button>
                }
              />
            ) : chat.turns.length === 0 ? (
              <div className="py-6">
                <h2 className="text-sm font-semibold text-ink">Ask a compliance question</h2>
                <p className="mt-1 text-[13px] text-ink-2">
                  Answers are grounded in the indexed documents, and every claim carries a
                  citation you can open and read.
                </p>
                <ul className="mt-4 space-y-1.5">
                  {SUGGESTED_QUESTIONS.map((question) => (
                    <li key={question}>
                      <button
                        type="button"
                        onClick={() => submit(question)}
                        className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-left text-[13px] text-ink-2 transition-colors hover:border-accent/40 hover:bg-accent-soft hover:text-ink"
                      >
                        {question}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="space-y-6">
                {chat.turns.map((turn) => (
                  <Turn
                    key={turn.id}
                    turn={turn}
                    onCitationClick={setActiveCitation}
                    onRetry={() => chat.retryLast()}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-border bg-surface px-4 py-3">
          <form
            className="mx-auto flex w-full max-w-3xl items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              submit(draft);
            }}
          >
            <label htmlFor="question" className="sr-only">
              Your compliance question
            </label>
            <textarea
              id="question"
              ref={composerRef}
              rows={1}
              value={draft}
              disabled={corpusEmpty}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                // Enter sends; Shift+Enter inserts a newline.
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit(draft);
                }
              }}
              placeholder={corpusEmpty ? "Index a document first…" : "Ask about the indexed compliance documents…"}
              className="max-h-40 min-h-[2.5rem] flex-1 resize-y rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none disabled:opacity-60"
            />
            {chat.isStreaming ? (
              <Button
                type="button"
                variant="secondary"
                onClick={chat.stop}
                icon={<Square className="size-3.5" aria-hidden />}
              >
                Stop
              </Button>
            ) : (
              <Button
                type="submit"
                variant="primary"
                disabled={!draft.trim() || corpusEmpty}
                icon={<ArrowUp className="size-4" aria-hidden />}
                aria-label="Send question"
              >
                Send
              </Button>
            )}
          </form>
          <p className="mx-auto mt-2 max-w-3xl text-[11px] text-ink-3">
            Reports what the indexed documents say. Verify citations before relying on an
            answer — this is not legal advice.
          </p>
        </div>
      </div>

      {/* Source panel: side-by-side on desktop, full-width sheet below lg. */}
      {activeCitation && (
        <div className="fixed inset-0 z-40 flex bg-canvas lg:static lg:z-auto lg:inset-auto">
          <SourcePanel citation={activeCitation} onClose={() => setActiveCitation(null)} />
        </div>
      )}
    </div>
  );
}

function Turn({
  turn,
  onCitationClick,
  onRetry,
}: {
  turn: ChatTurn;
  onCitationClick: (citation: Citation) => void;
  onRetry: () => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm text-white">
          {turn.content}
        </p>
      </div>
    );
  }

  const citations = turn.citations ?? [];

  return (
    <div className="space-y-3">
      {turn.retrieval?.rewritten_question && (
        <p className="text-[11px] text-ink-3">
          Searched as: <span className="text-ink-2">{turn.retrieval.rewritten_question}</span>
        </p>
      )}

      {turn.conflicts && turn.conflicts.length > 0 && (
        <ConflictCallout conflicts={turn.conflicts} />
      )}

      {turn.error ? (
        <Notice tone="danger" title="This answer could not be generated">
          <p>{turn.error.message}</p>
          <p className="mt-1 font-mono text-[11px] opacity-80">{turn.error.code}</p>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            onClick={onRetry}
            icon={<RotateCcw className="size-3.5" aria-hidden />}
          >
            Retry
          </Button>
        </Notice>
      ) : (
        <>
          {/* Streaming answers are announced politely so screen readers follow along. */}
          <div aria-live="polite" aria-atomic="false">
            <AnswerBody
              content={turn.content}
              citations={citations}
              onCitationClick={onCitationClick}
            />
            {turn.streaming && <span className="stream-caret" aria-label="Generating" />}
          </div>

          {!turn.streaming && (
            <>
              <SourceList citations={citations} onCitationClick={onCitationClick} />
              {turn.evidence && <EvidenceBadge evidence={turn.evidence} />}
              <TurnFooter turn={turn} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function TurnFooter({ turn }: { turn: ChatTurn }) {
  const timings = turn.timings;
  if (!timings && !turn.model) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[11px] text-ink-3">
      {turn.model && <span className="font-mono">{turn.model}</span>}
      {timings?.total_ms !== undefined && (
        <span className="tnum">total {formatMs(timings.total_ms)}</span>
      )}
      {timings?.retrieval_ms !== undefined && (
        <span className="tnum">retrieval {formatMs(timings.retrieval_ms)}</span>
      )}
      {timings?.rerank_ms ? <span className="tnum">rerank {formatMs(timings.rerank_ms)}</span> : null}
      {timings?.llm_ttft_ms ? (
        <span className="tnum">first token {formatMs(timings.llm_ttft_ms)}</span>
      ) : null}
      <span className="tnum">{formatTokens(turn.tokenUsage)}</span>
      {turn.refused && (
        <Badge tone="neutral" className={cn("text-[10px]")}>
          refused — insufficient evidence
        </Badge>
      )}
    </div>
  );
}
