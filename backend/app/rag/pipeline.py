"""The RAG pipeline — one place where a question becomes a grounded answer.

This replaces v1's `run_query` and keeps its most important property: **every code path,
including every failure path, produces the same result shape.** Errors surface in the `error`
field; nothing raises past this boundary and nothing prints.

Dependencies are injected (retriever, provider factory, settings) rather than constructed
inline, which is what lets the unit tests run with a fake embedder and fake LLM in
milliseconds, and lets the evaluation harness exercise this exact code rather than an
approximation of it.

Two entry points over identical retrieval and guardrails:
  * `answer()` — JSON mode, used by the CLI, the non-streaming API, and evaluation.
  * `answer_stream()` — marker mode, used by the chat UI (README DR-10).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.errors import LLMError, ValidationError
from app.core.logging import get_logger
from app.models import (
    AnswerResult,
    Evidence,
    LLMAnswer,
    RetrievalFilters,
    RetrievedChunk,
    StageTimings,
    TokenUsage,
    utc_now_iso,
)
from app.rag.citations import CitationResolver, MarkerStreamParser, resolve_used_ids
from app.rag.context import select_context
from app.rag.guardrails import (
    compute_evidence,
    detect_conflicts,
    has_sufficient_evidence,
    is_refusal,
)
from app.rag.llm import LLMProvider
from app.rag.prompts import (
    QUERY_REWRITE_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    SYSTEM_PROMPT_JSON,
    SYSTEM_PROMPT_STREAM,
    build_refusal_answer,
    build_user_prompt,
)
from app.rag.query_processing import build_rewrite_prompt, looks_like_followup, normalise_question
from app.rag.retrieval import HybridRetriever
from pydantic import ValidationError as PydanticValidationError

log = get_logger("rag")

ProviderFactory = Callable[[], LLMProvider]


@dataclass
class StreamEvent:
    type: str  # meta | retrieval | token | citations | evidence | conflicts | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AskOptions:
    k: int | None = None
    filters: RetrievalFilters | None = None
    history: list[tuple[str, str]] = field(default_factory=list)
    rewrite_followups: bool = True
    request_id: str | None = None
    conversation_id: str | None = None


class RagPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        retriever: HybridRetriever,
        provider_factory: ProviderFactory,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.provider_factory = provider_factory

    # ------------------------------------------------------------------
    # Shared stages
    # ------------------------------------------------------------------
    def _prepare_query(
        self, question: str, options: AskOptions, provider: LLMProvider | None
    ) -> tuple[str, str | None, int]:
        """Normalise, then rewrite follow-ups against conversation history.

        Returns (search_query, rewritten_or_None, elapsed_ms). A rewrite failure is never
        fatal — the original question is used instead.
        """
        started = time.perf_counter()
        clean = normalise_question(question, self.settings.max_question_chars)
        rewritten: str | None = None

        if (
            options.rewrite_followups
            and options.history
            and provider is not None
            and looks_like_followup(clean)
        ):
            try:
                raw = provider.generate_json(
                    QUERY_REWRITE_SYSTEM_PROMPT,
                    build_rewrite_prompt(clean, options.history),
                    timeout=min(20, self.settings.llm_timeout_seconds),
                    temperature=0.0,
                )
                candidate = str(raw.get("question", "")).strip()
                # Guard against a rewrite that collapses or explodes the question.
                if (
                    candidate
                    and 4 <= len(candidate) <= self.settings.max_question_chars
                    and candidate.lower() != clean.lower()
                ):
                    rewritten = candidate
            except Exception as exc:
                log.warning("query.rewrite_failed", error=str(exc))

        elapsed = int((time.perf_counter() - started) * 1000)
        return (rewritten or clean), rewritten, elapsed

    def _retrieve(self, search_query: str, options: AskOptions):
        return self.retriever.retrieve(
            search_query, k=options.k or self.settings.retrieval_top_k, filters=options.filters
        )

    def _refusal_result(
        self,
        *,
        question: str,
        rewritten: str | None,
        retrieved: list[RetrievedChunk],
        params: Any,
        timings: StageTimings,
        model: str,
        options: AskOptions,
    ) -> AnswerResult:
        """Retrieval-gated refusal: no answer is requested from the model at all.

        Refusal must not depend on the model choosing to refuse.
        """
        answer = build_refusal_answer(retrieved)
        evidence = compute_evidence(
            chunks=retrieved,
            cited_count=0,
            answer=answer,
            settings=self.settings,
            refused=True,
        )
        return AnswerResult(
            question=question,
            rewritten_question=rewritten,
            answer=answer,
            citations=[],
            evidence=evidence,
            conflicts=[],
            refused=True,
            model=model,
            timings=timings,
            retrieval_params=params,
            retrieved=retrieved,
            request_id=options.request_id,
        )

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------
    def answer(self, question: str, options: AskOptions | None = None) -> AnswerResult:
        options = options or AskOptions()
        started = time.perf_counter()
        timings = StageTimings()
        model_name = self.settings.active_model_name

        def finish(result: AnswerResult) -> AnswerResult:
            result.timings.total_ms = int((time.perf_counter() - started) * 1000)
            return result

        # --- provider -------------------------------------------------------
        try:
            provider = self.provider_factory()
            model_name = provider.model_name
        except LLMError as exc:
            return finish(self._error_result(question, exc.message, model_name, timings, options))

        # --- query processing ----------------------------------------------
        try:
            search_query, rewritten, timings.query_processing_ms = self._prepare_query(
                question, options, provider
            )
        except ValidationError as exc:
            return finish(self._error_result(question, exc.message, model_name, timings, options))

        # --- retrieval ------------------------------------------------------
        try:
            outcome = self._retrieve(search_query, options)
        except Exception as exc:
            log.error("retrieval.failed", error=str(exc), exc_info=True)
            return finish(
                self._error_result(question, f"Retrieval failed: {exc}", model_name, timings, options)
            )

        timings.retrieval_ms = outcome.retrieval_ms
        timings.rerank_ms = outcome.rerank_ms
        retrieved = outcome.chunks

        # --- evidence gate --------------------------------------------------
        if not has_sufficient_evidence(retrieved, self.settings):
            return finish(
                self._refusal_result(
                    question=question,
                    rewritten=rewritten,
                    retrieved=retrieved,
                    params=outcome.params,
                    timings=timings,
                    model=model_name,
                    options=options,
                )
            )

        # --- context selection ----------------------------------------------
        context_started = time.perf_counter()
        selected = select_context(retrieved, max_tokens=self.settings.context_max_tokens)
        timings.context_ms = int((time.perf_counter() - context_started) * 1000)

        # --- generation -----------------------------------------------------
        user_prompt = build_user_prompt(
            search_query, selected.chunks, history=options.history, streaming=False
        )
        llm_started = time.perf_counter()
        try:
            llm_answer = self._generate_json_with_repair(provider, user_prompt)
        except LLMError as exc:
            timings.llm_ms = int((time.perf_counter() - llm_started) * 1000)
            result = self._error_result(question, exc.message, model_name, timings, options)
            result.retrieved = retrieved
            result.retrieval_params = outcome.params
            result.rewritten_question = rewritten
            return finish(result)
        timings.llm_ms = int((time.perf_counter() - llm_started) * 1000)

        # --- validation + citations ------------------------------------------
        validation_started = time.perf_counter()
        citations, fabricated = resolve_used_ids(llm_answer.used_chunk_ids, selected.chunks)
        answer_text = llm_answer.answer.strip()
        refused = is_refusal(answer_text) or not citations
        evidence = compute_evidence(
            chunks=selected.chunks,
            cited_count=len(citations),
            answer=answer_text,
            settings=self.settings,
            refused=refused,
        )
        conflicts = detect_conflicts(selected.chunks)
        timings.validation_ms = int((time.perf_counter() - validation_started) * 1000)

        if fabricated:
            log.warning("llm.fabricated_citation_ids", ids=fabricated, model=model_name)

        return finish(
            AnswerResult(
                question=question,
                rewritten_question=rewritten,
                answer=answer_text,
                citations=citations,
                evidence=evidence,
                conflicts=conflicts,
                refused=refused,
                model=model_name,
                timings=timings,
                token_usage=provider.last_usage(),
                retrieval_params=outcome.params,
                retrieved=retrieved,
                request_id=options.request_id,
            )
        )

    def _generate_json_with_repair(self, provider: LLMProvider, user_prompt: str) -> LLMAnswer:
        """One normal attempt, then one stricter repair attempt.

        Preserved from v1: a model that returns slightly malformed JSON is common enough that
        a single retry is worth it, and a second failure is a real error worth surfacing.
        """
        try:
            raw = provider.generate_json(
                SYSTEM_PROMPT_JSON,
                user_prompt,
                timeout=self.settings.llm_timeout_seconds,
                temperature=self.settings.llm_temperature,
            )
            return LLMAnswer.model_validate(raw)
        except (LLMError, PydanticValidationError) as first_error:
            try:
                raw = provider.generate_json(
                    REPAIR_SYSTEM_PROMPT,
                    user_prompt,
                    timeout=self.settings.llm_timeout_seconds,
                    temperature=0.0,
                )
                return LLMAnswer.model_validate(raw)
            except (LLMError, PydanticValidationError) as second_error:
                raise LLMError(
                    "The model did not return a usable response after one repair attempt "
                    f"({type(first_error).__name__} then {type(second_error).__name__})."
                ) from second_error

    def _error_result(
        self,
        question: str,
        error: str,
        model: str,
        timings: StageTimings,
        options: AskOptions,
    ) -> AnswerResult:
        return AnswerResult(
            question=question,
            answer="",
            citations=[],
            evidence=Evidence(band="insufficient", basis="The query could not be completed."),
            model=model,
            timings=timings,
            request_id=options.request_id,
            timestamp=utc_now_iso(),
            error=error,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    def answer_stream(self, question: str, options: AskOptions | None = None) -> Iterator[StreamEvent]:
        """Yield events in a fixed order: meta → retrieval → token* → citations → evidence
        → conflicts → done. An error event replaces whatever would have followed.

        The final `done` payload carries the complete AnswerResult so the caller can persist
        the message and write the audit entry without reassembling the stream.
        """
        options = options or AskOptions()
        started = time.perf_counter()
        timings = StageTimings()
        model_name = self.settings.active_model_name

        try:
            provider = self.provider_factory()
            model_name = provider.model_name
        except LLMError as exc:
            yield StreamEvent("error", {"code": exc.code, "message": exc.message})
            return

        yield StreamEvent(
            "meta",
            {
                "model": model_name,
                "request_id": options.request_id,
                "conversation_id": options.conversation_id,
            },
        )

        # --- query processing + retrieval -----------------------------------
        try:
            search_query, rewritten, timings.query_processing_ms = self._prepare_query(
                question, options, provider
            )
            outcome = self._retrieve(search_query, options)
        except ValidationError as exc:
            yield StreamEvent("error", {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:
            log.error("stream.retrieval_failed", error=str(exc), exc_info=True)
            yield StreamEvent("error", {"code": "retrieval_failed", "message": str(exc)})
            return

        timings.retrieval_ms = outcome.retrieval_ms
        timings.rerank_ms = outcome.rerank_ms
        retrieved = outcome.chunks

        yield StreamEvent(
            "retrieval",
            {
                "rewritten_question": rewritten,
                "n_retrieved": len(retrieved),
                "retrieval_ms": outcome.retrieval_ms,
                "rerank_ms": outcome.rerank_ms,
                "sources": [
                    {
                        "chunk_uid": rc.chunk.chunk_uid,
                        "label": rc.chunk.metadata.citation_label,
                        "document_id": rc.chunk.metadata.document_id,
                        "score": round(rc.normalised_score, 4),
                    }
                    for rc in retrieved
                ],
            },
        )

        # --- evidence gate --------------------------------------------------
        if not has_sufficient_evidence(retrieved, self.settings):
            result = self._refusal_result(
                question=question,
                rewritten=rewritten,
                retrieved=retrieved,
                params=outcome.params,
                timings=timings,
                model=model_name,
                options=options,
            )
            result.timings.total_ms = int((time.perf_counter() - started) * 1000)
            yield StreamEvent("token", {"text": result.answer})
            yield StreamEvent("citations", {"citations": []})
            yield StreamEvent("evidence", result.evidence.model_dump(mode="json"))
            yield StreamEvent("done", {"result": result.model_dump(mode="json"), "_result": result})
            return

        # --- context + generation -------------------------------------------
        context_started = time.perf_counter()
        selected = select_context(retrieved, max_tokens=self.settings.context_max_tokens)
        timings.context_ms = int((time.perf_counter() - context_started) * 1000)

        user_prompt = build_user_prompt(
            search_query, selected.chunks, history=options.history, streaming=True
        )

        resolver = CitationResolver(selected.chunks)
        parser = MarkerStreamParser(resolver)
        rendered: list[str] = []
        llm_started = time.perf_counter()
        first_token_at: float | None = None

        try:
            for delta in provider.stream_text(
                SYSTEM_PROMPT_STREAM,
                user_prompt,
                timeout=self.settings.llm_timeout_seconds,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_answer_tokens,
            ):
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                    timings.llm_ttft_ms = int((first_token_at - llm_started) * 1000)
                visible = parser.feed(delta)
                if visible:
                    rendered.append(visible)
                    yield StreamEvent("token", {"text": visible})

            tail = parser.flush()
            if tail:
                rendered.append(tail)
                yield StreamEvent("token", {"text": tail})
        except LLMError as exc:
            yield StreamEvent("error", {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:
            log.error("stream.generation_failed", error=str(exc), exc_info=True)
            yield StreamEvent("error", {"code": "llm_unavailable", "message": str(exc)})
            return

        timings.llm_ms = int((time.perf_counter() - llm_started) * 1000)

        # --- validation ------------------------------------------------------
        validation_started = time.perf_counter()
        answer_text = "".join(rendered).strip()
        citations = resolver.citations()
        refused = is_refusal(answer_text) or not citations
        evidence = compute_evidence(
            chunks=selected.chunks,
            cited_count=len(citations),
            answer=answer_text,
            settings=self.settings,
            refused=refused,
        )
        conflicts = detect_conflicts(selected.chunks)
        timings.validation_ms = int((time.perf_counter() - validation_started) * 1000)
        timings.total_ms = int((time.perf_counter() - started) * 1000)

        if resolver.fabricated:
            log.warning("llm.fabricated_citation_ids", ids=resolver.fabricated, model=model_name)

        result = AnswerResult(
            question=question,
            rewritten_question=rewritten,
            answer=answer_text,
            citations=citations,
            evidence=evidence,
            conflicts=conflicts,
            refused=refused,
            model=model_name,
            timings=timings,
            token_usage=provider.last_usage() or TokenUsage(),
            retrieval_params=outcome.params,
            retrieved=retrieved,
            request_id=options.request_id,
        )

        yield StreamEvent("citations", {"citations": [c.model_dump(mode="json") for c in citations]})
        yield StreamEvent("evidence", evidence.model_dump(mode="json"))
        if conflicts:
            yield StreamEvent("conflicts", {"conflicts": [c.model_dump(mode="json") for c in conflicts]})
        yield StreamEvent("done", {"result": result.model_dump(mode="json"), "_result": result})
