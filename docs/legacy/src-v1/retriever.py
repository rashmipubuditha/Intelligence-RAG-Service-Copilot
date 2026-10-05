"""Hybrid retriever: dense (FAISS) + sparse (BM25), fused with Reciprocal Rank Fusion.

Why hybrid: compliance text is terminology-dense ("PEP", "EDD", "MLRO", "Section 4").
Dense embeddings smooth rare tokens into nearby concepts and occasionally pull the wrong
policy for keyword-driven queries. BM25 alone misses paraphrased questions. RRF gives us
both legs without having to calibrate raw scores from two different scales.
"""

from __future__ import annotations

import re

import numpy as np

from src.embedder import Embedder
from src.schemas import RetrievedChunk
from src.vector_store import VectorStore

_TOKEN = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        candidate_pool: int = 20,
        rrf_k: int = 60,
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.candidate_pool = candidate_pool
        self.rrf_k = rrf_k

        from rank_bm25 import BM25Okapi

        tokenized = [_tokenize(c.text) for c in vector_store.chunks]
        self.bm25 = BM25Okapi(tokenized) if tokenized else None

    def retrieve(self, question: str, k: int = 3) -> list[RetrievedChunk]:
        if not self.vector_store.chunks:
            return []

        pool = min(self.candidate_pool, len(self.vector_store.chunks))

        # --- dense leg ---
        q_emb = self.embedder.encode([question])
        dense_hits = self.vector_store.search(q_emb, pool)
        dense_ranks: dict[int, int] = {
            chunk.chunk_id: rank for rank, (chunk, _score) in enumerate(dense_hits)
        }

        # --- sparse leg ---
        sparse_ranks: dict[int, int] = {}
        if self.bm25 is not None:
            scores = self.bm25.get_scores(_tokenize(question))
            top_idx = np.argsort(scores)[::-1][:pool]
            for rank, idx in enumerate(top_idx):
                if scores[idx] <= 0:
                    continue
                cid = self.vector_store.chunks[int(idx)].chunk_id
                sparse_ranks[cid] = rank

        # --- RRF fusion ---
        fused: dict[int, float] = {}
        for cid, rank in dense_ranks.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (self.rrf_k + rank)
        for cid, rank in sparse_ranks.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (self.rrf_k + rank)

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]

        chunk_by_id = {c.chunk_id: c for c in self.vector_store.chunks}
        return [
            RetrievedChunk(chunk=chunk_by_id[cid], score=score)
            for cid, score in ranked
        ]
