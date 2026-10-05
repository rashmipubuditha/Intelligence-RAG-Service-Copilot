"""Chat orchestration: conversation memory, RAG invocation, persistence, audit, metrics.

The pipeline answers questions; this service decides what a *conversation* is — which turns
form the rewrite history, what gets persisted, what gets audited, and what gets counted. That
separation is why the pipeline stays framework-free and directly unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.core.errors import IndexNotReadyError, NotFoundError
from app.core.logging import get_logger, hash_text
from app.models import AnswerResult, RetrievalFilters
from app.observability.audit import audit_answer
from app.observability.metrics import metrics
from app.rag.pipeline import AskOptions, StreamEvent

if TYPE_CHECKING:
    from app.container import AppContainer

log = get_logger("chat")


class ChatService:
    def __init__(self, *, container: AppContainer) -> None:
        self.c = container

    # ------------------------------------------------------------------
    def _prepare(
        self,
        question: str,
        conversation_id: str | None,
        *,
        filters: RetrievalFilters | None,
        k: int | None,
        request_id: str | None,
        use_history: bool,
    ) -> tuple[str, AskOptions]:
        if self.c.chunks.count() == 0:
            raise IndexNotReadyError()

        if conversation_id:
            if not self.c.conversations.exists(conversation_id):
                raise NotFoundError(f"Conversation {conversation_id} does not exist.")
        else:
            conversation_id = self.c.conversations.create()

        history = self.c.conversations.recent_turns(conversation_id, turns=4) if use_history else []
        options = AskOptions(
            k=k,
            filters=filters,
            history=history,
            request_id=request_id,
            conversation_id=conversation_id,
        )
        return conversation_id, options

    def _persist_and_record(self, conversation_id: str, question: str, result: AnswerResult) -> None:
        self.c.conversations.add_message(conversation_id, "user", question)
        self.c.conversations.add_message(
            conversation_id,
            "assistant",
            result.answer,
            model=result.model,
            evidence=result.evidence.model_dump(mode="json"),
            conflicts=[c.model_dump(mode="json") for c in result.conflicts],
            citations=[c.model_dump(mode="json") for c in result.citations],
            retrieval_params=result.retrieval_params.model_dump(mode="json")
            if result.retrieval_params
            else None,
            timings=result.timings.model_dump(mode="json"),
            token_usage=result.token_usage.model_dump(mode="json"),
            refused=result.refused,
            request_id=result.request_id,
            error=result.error,
        )

        # Audit log: full question + full retrieved context, by design (README §16).
        audit_answer(self.c.settings.audit_log_path, result, conversation_id=conversation_id)

        # Analytics: hash only — never the question body.
        self.c.query_log.record(
            request_id=result.request_id,
            question_hash=hash_text(result.question),
            question_len=len(result.question),
            top_k=result.retrieval_params.top_k if result.retrieval_params else 0,
            rerank_enabled=result.retrieval_params.rerank_enabled if result.retrieval_params else False,
            model=result.model,
            n_retrieved=len(result.retrieved),
            n_cited=len(result.citations),
            evidence_band=result.evidence.band,
            refused=result.refused,
            retrieval_ms=result.timings.retrieval_ms,
            rerank_ms=result.timings.rerank_ms,
            llm_ms=result.timings.llm_ms,
            total_ms=result.timings.total_ms,
            prompt_tokens=result.token_usage.prompt_tokens,
            completion_tokens=result.token_usage.completion_tokens,
            error_code="error" if result.error else None,
        )

        metrics.increment("rag_queries_total", band=result.evidence.band)
        if result.refused:
            metrics.increment("rag_refusals_total")
        if result.error:
            metrics.increment("rag_errors_total")
        metrics.observe("rag_total", result.timings.total_ms)
        metrics.observe("rag_retrieval", result.timings.retrieval_ms)
        if result.timings.llm_ms:
            metrics.observe("rag_llm", result.timings.llm_ms)

        log.info(
            "chat.answered",
            question_hash=hash_text(result.question),
            question_len=len(result.question),
            n_retrieved=len(result.retrieved),
            n_cited=len(result.citations),
            band=result.evidence.band,
            refused=result.refused,
            conflicts=len(result.conflicts),
            model=result.model,
            retrieval_ms=result.timings.retrieval_ms,
            rerank_ms=result.timings.rerank_ms,
            llm_ms=result.timings.llm_ms,
            ttft_ms=result.timings.llm_ttft_ms,
            total_ms=result.timings.total_ms,
            error=result.error,
        )

    # ------------------------------------------------------------------
    def ask(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        filters: RetrievalFilters | None = None,
        k: int | None = None,
        request_id: str | None = None,
        use_history: bool = True,
        persist: bool = True,
    ) -> tuple[str, AnswerResult]:
        """Non-streaming answer. Returns (conversation_id, result)."""
        conversation_id, options = self._prepare(
            question,
            conversation_id,
            filters=filters,
            k=k,
            request_id=request_id,
            use_history=use_history,
        )
        result = self.c.rag.answer(question, options)
        if persist:
            self._persist_and_record(conversation_id, question, result)
        return conversation_id, result

    def ask_stream(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        filters: RetrievalFilters | None = None,
        k: int | None = None,
        request_id: str | None = None,
        use_history: bool = True,
    ) -> Iterator[StreamEvent]:
        """Streaming answer. Persistence and audit happen on the terminal event, so a
        cancelled stream still records whatever was produced."""
        conversation_id, options = self._prepare(
            question,
            conversation_id,
            filters=filters,
            k=k,
            request_id=request_id,
            use_history=use_history,
        )
        yield StreamEvent("conversation", {"conversation_id": conversation_id})

        completed = False
        for event in self.c.rag.answer_stream(question, options):
            if event.type == "done":
                completed = True
                result: AnswerResult = event.data.pop("_result")
                self._persist_and_record(conversation_id, question, result)
                event.data["conversation_id"] = conversation_id
            yield event

        if not completed:
            metrics.increment("rag_streams_incomplete_total")

    # ------------------------------------------------------------------
    def list_conversations(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.c.conversations.list(limit=limit, offset=offset)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        conversation = self.c.conversations.get(conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} does not exist.")
        conversation["messages"] = self.c.conversations.messages(conversation_id)
        return conversation

    def delete_conversation(self, conversation_id: str) -> None:
        if not self.c.conversations.exists(conversation_id):
            raise NotFoundError(f"Conversation {conversation_id} does not exist.")
        # The audit log deliberately retains the queries; only the UI transcript is removed.
        self.c.conversations.delete(conversation_id)
