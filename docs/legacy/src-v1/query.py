"""Query orchestrator.

Pipeline: load store → retrieve top-k → build prompt → LLM call (with one repair retry)
→ filter fabricated chunk IDs → assemble citations → write audit entry → return response.

Design contract: this function always returns a QueryResponse with the same schema, on
*every* code path including failure. Errors are surfaced through the `error` field, never
by raising or by printing plain text. Auditing happens before return on every path.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.audit import write_audit_entry
from src.config import Settings
from src.embedder import Embedder
from src.llm import LLMError, LLMProvider, build_provider
from src.prompts import REPAIR_SYSTEM_PROMPT, SYSTEM_PROMPT, build_user_prompt
from src.retriever import HybridRetriever
from src.schemas import (
    AuditEntry,
    Chunk,
    Citation,
    LLMAnswer,
    QueryResponse,
    RetrievedChunk,
)
from src.vector_store import VectorStore


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_response(question: str, error: str, model: str, latency_ms: int) -> QueryResponse:
    return QueryResponse(
        question=question,
        answer="",
        citations=[],
        model=model,
        latency_ms=latency_ms,
        timestamp=_iso_utc_now(),
        error=error,
    )


def _safe_audit(
    audit_path: Path,
    response: QueryResponse,
    retrieved_chunks: list[Chunk],
) -> None:
    entry = AuditEntry(
        question=response.question,
        response=response,
        retrieved_context=retrieved_chunks,
        model=response.model,
        latency_ms=response.latency_ms,
        timestamp=response.timestamp,
        error=response.error,
    )
    try:
        write_audit_entry(audit_path, entry)
    except Exception as e:  # never break the query path because of audit failure
        print(f"[audit] failed to write audit entry: {e}", file=sys.stderr)


def _call_llm_validated(
    provider: LLMProvider, system_prompt: str, user_prompt: str, timeout: int
) -> LLMAnswer:
    raw = provider.generate_json(system_prompt, user_prompt, timeout=timeout)
    return LLMAnswer.model_validate(raw)


def _call_llm_with_repair(
    provider: LLMProvider, user_prompt: str, timeout: int
) -> LLMAnswer:
    """One normal attempt, then one repair attempt with a stricter system prompt."""
    try:
        return _call_llm_validated(provider, SYSTEM_PROMPT, user_prompt, timeout)
    except (LLMError, ValidationError) as first_err:
        try:
            return _call_llm_validated(provider, REPAIR_SYSTEM_PROMPT, user_prompt, timeout)
        except (LLMError, ValidationError) as second_err:
            raise LLMError(
                f"LLM failed after one repair attempt. first={first_err}; repair={second_err}"
            ) from second_err


def run_query(
    question: str,
    k: int,
    settings: Settings,
    audit_path: Path,
) -> QueryResponse:
    started = time.perf_counter()
    model_name = settings.active_model_name
    retrieved: list[RetrievedChunk] = []

    # --- 1. load vector store ---
    try:
        store = VectorStore.load(settings.vector_store_dir)
    except FileNotFoundError as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp = _error_response(question, str(e), model_name, latency_ms)
        _safe_audit(audit_path, resp, [])
        return resp

    # --- 2. retrieve top-k ---
    try:
        embedder = Embedder(settings.embedding_model)
        retriever = HybridRetriever(store, embedder)
        retrieved = retriever.retrieve(question, k=k)
    except Exception as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        err = f"Retrieval failed: {e}"
        resp = _error_response(question, err, model_name, latency_ms)
        _safe_audit(audit_path, resp, [])
        return resp

    retrieved_chunks: list[Chunk] = [rc.chunk for rc in retrieved]

    # --- 3. build LLM provider ---
    try:
        provider = build_provider(settings)
        model_name = provider.model_name
    except LLMError as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp = _error_response(question, str(e), model_name, latency_ms)
        _safe_audit(audit_path, resp, retrieved_chunks)
        return resp

    # --- 4. LLM call + validation + one repair attempt ---
    user_prompt = build_user_prompt(question, retrieved)
    try:
        llm_answer = _call_llm_with_repair(
            provider, user_prompt, timeout=settings.llm_timeout_seconds
        )
    except LLMError as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp = _error_response(question, str(e), model_name, latency_ms)
        _safe_audit(audit_path, resp, retrieved_chunks)
        return resp

    # --- 5. assemble citations from used_chunk_ids — drop anything the LLM fabricated ---
    chunks_by_id = {rc.chunk.chunk_id: rc.chunk for rc in retrieved}
    citations: list[Citation] = []
    fabricated_ids: list[int] = []
    seen_ids: set[int] = set()
    for cid in llm_answer.used_chunk_ids:
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        chunk = chunks_by_id.get(cid)
        if chunk is None:
            fabricated_ids.append(cid)
            continue
        citations.append(Citation(document=chunk.document, chunk=chunk.text))

    if fabricated_ids:
        print(
            f"[query] dropped fabricated chunk_ids from LLM: {fabricated_ids}",
            file=sys.stderr,
        )

    # --- 6. assemble + audit + return ---
    latency_ms = int((time.perf_counter() - started) * 1000)
    response = QueryResponse(
        question=question,
        answer=llm_answer.answer,
        citations=citations,
        model=model_name,
        latency_ms=latency_ms,
        timestamp=_iso_utc_now(),
        error=None,
    )
    _safe_audit(audit_path, response, retrieved_chunks)
    return response
