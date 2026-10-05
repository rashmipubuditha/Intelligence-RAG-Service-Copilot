"""Hybrid retrieval: metadata filter → dense + sparse → RRF → rerank.

The v1 algorithm (FAISS top-20 + BM25 top-20 fused by Reciprocal Rank Fusion) is preserved
exactly; `RERANK_ENABLED=false` with default parameters reproduces it. What is added:

  * **Metadata pre-filtering** before ranking. Filtering afterwards would silently return
    fewer than k results, and a superseded policy must not be retrievable as a current rule.
  * **Settings-driven parameters** (candidate pool, rrf_k, leg weights) recorded on every
    answer, so an experiment can be reconstructed from its result (fixes README D8).
  * **Reranking** as an optional stage over the fused pool.
  * **Deduplication** of exact and near-duplicate passages, which the 60-word chunk overlap
    and re-uploaded document versions would otherwise push into the context window.

Why RRF rather than score blending: cosine similarities and BM25 scores live on different,
corpus-dependent scales. Rank fusion needs no calibration, which is what makes it robust
when the corpus changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import Chunk, RetrievalFilters, RetrievalParams, RetrievedChunk
from app.rag.embedder import Embedder
from app.rag.query_processing import expand_acronyms
from app.rag.reranker import Reranker
from app.storage.bm25_store import BM25Store
from app.storage.repositories import ChunkRepository
from app.storage.vector_store import VectorStore

log = get_logger("retrieval")


@dataclass
class RetrievalOutcome:
    chunks: list[RetrievedChunk]
    params: RetrievalParams
    retrieval_ms: int = 0
    rerank_ms: int = 0
    diagnostics: dict[str, object] = field(default_factory=dict)


def reciprocal_rank_fusion(ranked_lists: list[tuple[list[int], float]], rrf_k: int = 60) -> dict[int, float]:
    """Fuse ranked id lists. Each entry is (ids_best_first, weight).

    score(d) = Σ weight_l / (rrf_k + rank_of_d_in_l)
    """
    fused: dict[int, float] = {}
    for ids, weight in ranked_lists:
        if weight <= 0:
            continue
        for rank, doc_id in enumerate(ids):
            fused[doc_id] = fused.get(doc_id, 0.0) + weight / (rrf_k + rank)
    return fused


def deduplicate(chunks: list[RetrievedChunk], threshold: float = 0.97) -> tuple[list[RetrievedChunk], int]:
    """Drop exact and near-duplicate passages, keeping the better-ranked copy.

    Near-duplicate detection uses token-set Jaccard similarity rather than embeddings: it is
    free, deterministic, and at chunk granularity it catches precisely the overlap-induced
    repetition we care about.
    """
    kept: list[RetrievedChunk] = []
    seen_hashes: set[str] = set()
    seen_tokens: list[set[str]] = []
    dropped = 0

    for rc in chunks:
        digest = rc.chunk.metadata.content_sha256 or rc.chunk.text
        if digest in seen_hashes:
            dropped += 1
            continue
        tokens = set(rc.chunk.text.lower().split())
        is_duplicate = False
        for previous in seen_tokens:
            union = tokens | previous
            if not union:
                continue
            if len(tokens & previous) / len(union) >= threshold:
                is_duplicate = True
                break
        if is_duplicate:
            dropped += 1
            continue
        seen_hashes.add(digest)
        seen_tokens.append(tokens)
        kept.append(rc)

    return kept, dropped


class HybridRetriever:
    def __init__(
        self,
        *,
        settings: Settings,
        vector_store: VectorStore,
        bm25: BM25Store,
        chunks: ChunkRepository,
        embedder: Embedder,
        reranker: Reranker,
    ) -> None:
        self.settings = settings
        self.vector_store = vector_store
        self.bm25 = bm25
        self.chunks = chunks
        self.embedder = embedder
        self.reranker = reranker

    def retrieve(
        self,
        query: str,
        *,
        k: int | None = None,
        filters: RetrievalFilters | None = None,
        candidate_pool: int | None = None,
    ) -> RetrievalOutcome:
        settings = self.settings
        k = k or settings.retrieval_top_k
        pool = candidate_pool or settings.retrieval_candidate_pool
        filters = filters or RetrievalFilters()

        params = RetrievalParams(
            top_k=k,
            candidate_pool=pool,
            rrf_k=settings.rrf_k,
            rerank_enabled=bool(getattr(self.reranker, "enabled", False)),
            rerank_model=getattr(self.reranker, "model_name", None),
            embedding_model=self.embedder.model_name,
            filters=filters.as_dict(),
        )

        if self.vector_store.ntotal == 0:
            return RetrievalOutcome(chunks=[], params=params)

        started = time.perf_counter()

        # --- 1. metadata pre-filter -----------------------------------------
        allowed = self.chunks.allowed_faiss_ids(filters)
        if allowed is not None and not allowed:
            return RetrievalOutcome(
                chunks=[],
                params=params,
                retrieval_ms=int((time.perf_counter() - started) * 1000),
                diagnostics={"filtered_to_empty": True},
            )

        # --- 2. dense leg ---------------------------------------------------
        query_vector = self.embedder.encode_query(query)
        dense_hits = self.vector_store.search(query_vector, pool, allowed_ids=allowed)
        dense_ids = [fid for fid, _ in dense_hits]
        dense_scores = dict(dense_hits)

        # --- 3. sparse leg (acronym-expanded; BM25 is literal) --------------
        sparse_hits = self.bm25.search(expand_acronyms(query), pool, allowed_ids=allowed)
        sparse_ids = [fid for fid, _ in sparse_hits]
        sparse_scores = dict(sparse_hits)

        # --- 4. RRF fusion --------------------------------------------------
        fused = reciprocal_rank_fusion(
            [
                (dense_ids, settings.rrf_dense_weight),
                (sparse_ids, settings.rrf_sparse_weight),
            ],
            rrf_k=settings.rrf_k,
        )
        if not fused:
            return RetrievalOutcome(
                chunks=[], params=params, retrieval_ms=int((time.perf_counter() - started) * 1000)
            )

        ordered_ids = sorted(fused, key=lambda fid: fused[fid], reverse=True)[:pool]
        chunk_by_id: dict[int, Chunk] = self.chunks.get_by_faiss_ids(ordered_ids)

        dense_rank_by_id = {fid: rank for rank, fid in enumerate(dense_ids)}
        sparse_rank_by_id = {fid: rank for rank, fid in enumerate(sparse_ids)}

        candidates: list[RetrievedChunk] = []
        for fid in ordered_ids:
            chunk = chunk_by_id.get(fid)
            if chunk is None:  # registry/index drift — reconciliation will clean it up
                continue
            candidates.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=fused[fid],
                    rrf_score=fused[fid],
                    dense_rank=dense_rank_by_id.get(fid),
                    sparse_rank=sparse_rank_by_id.get(fid),
                )
            )

        retrieval_ms = int((time.perf_counter() - started) * 1000)

        # --- 5. rerank ------------------------------------------------------
        rerank_started = time.perf_counter()
        reranked = self.reranker.rerank(query, candidates)
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000) if params.rerank_enabled else 0

        # --- 6. dedup + trim ------------------------------------------------
        deduped, dropped = deduplicate(reranked, settings.dedup_similarity_threshold)
        final = deduped[:k]

        params.n_candidates = len(candidates)
        params.n_retrieved = len(final)
        params.n_dropped_duplicates = dropped

        diagnostics = {
            "dense_hits": len(dense_ids),
            "sparse_hits": len(sparse_ids),
            "leg_overlap": len(set(dense_ids) & set(sparse_ids)),
            "top_dense_score": round(max(dense_scores.values()), 4) if dense_scores else 0.0,
            "top_sparse_score": round(max(sparse_scores.values()), 4) if sparse_scores else 0.0,
            "filtered": allowed is not None,
            "duplicates_dropped": dropped,
        }
        log.debug("retrieval.done", k=k, pool=pool, **diagnostics)

        return RetrievalOutcome(
            chunks=final,
            params=params,
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            diagnostics=diagnostics,
        )
