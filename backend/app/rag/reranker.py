"""Cross-encoder reranking.

Why a reranker at all: a bi-encoder compresses a passage into one vector *before* it has
seen the query, so it cannot weigh which part of a passage matters for this question. A
cross-encoder reads query and passage jointly and is markedly better at precision near the
top of the list — which is the only part the LLM ever sees.

Why it is disabled by default: README DR-7. It ships enabled only if the evaluation harness
shows a material Precision@3 / MRR / nDCG gain over RRF-only on the golden set. A feature
flag plus a published measurement is honest; an unmeasured feature is not.

`NoopReranker` is a true no-op (it does not even reorder), so `RERANK_ENABLED=false`
reproduces the RRF-only baseline exactly.
"""

from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger
from app.models import RetrievedChunk

log = get_logger("rerank")

_CACHE: dict[str, CrossEncoderReranker] = {}


class Reranker(Protocol):
    enabled: bool
    model_name: str | None

    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class NoopReranker:
    enabled = False
    model_name = None

    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return candidates


class CrossEncoderReranker:
    def __init__(self, model_name: str, top_n: int = 30) -> None:
        self.enabled = True
        self.model_name = model_name
        self.top_n = top_n
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def warm_up(self) -> None:
        self._load().predict([("warm", "up")])

    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Score each candidate jointly with the query and re-sort.

        `score` becomes the rerank score so downstream code has one ranking signal, while
        `rrf_score` is preserved for diagnostics and for the evaluation A/B.
        """
        if not candidates:
            return []
        pool = candidates[: self.top_n]
        model = self._load()
        pairs = [(query, rc.chunk.text) for rc in pool]
        try:
            scores = model.predict(pairs, show_progress_bar=False)
        except Exception as exc:
            # A reranker failure must degrade to the fused ranking, never fail the query.
            log.warning("rerank.failed", error=str(exc), model=self.model_name)
            return candidates

        reranked: list[RetrievedChunk] = []
        for rc, score in zip(pool, scores, strict=True):
            reranked.append(rc.model_copy(update={"rerank_score": float(score), "score": float(score)}))
        reranked.sort(key=lambda rc: rc.rerank_score or 0.0, reverse=True)
        return reranked


def build_reranker(*, enabled: bool, model_name: str, top_n: int) -> Reranker:
    if not enabled:
        return NoopReranker()
    key = f"{model_name}|{top_n}"
    if key not in _CACHE:
        _CACHE[key] = CrossEncoderReranker(model_name, top_n=top_n)
    return _CACHE[key]
