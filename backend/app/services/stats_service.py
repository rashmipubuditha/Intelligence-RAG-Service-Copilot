"""Dashboard aggregates.

Everything here is measured from the registry, the query log, and the indices — there are no
placeholder or synthetic numbers in this service. If a figure is unknown it is reported as
zero or null rather than invented.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.observability.metrics import metrics

if TYPE_CHECKING:
    from app.container import AppContainer


class StatsService:
    def __init__(self, *, container: AppContainer) -> None:
        self.c = container

    def dashboard(self) -> dict[str, Any]:
        documents = self.c.documents
        query_stats = self.c.query_log.stats()
        total_queries = query_stats["queries_total"]

        return {
            "documents": {
                "total": documents.count(),
                "active": documents.count(status="indexed"),
                "processing": documents.count(status="processing"),
                "failed": documents.count(status="failed"),
                "inactive": documents.count(status="inactive"),
            },
            "index": {
                "chunks": self.c.chunks.count(),
                "vectors": self.c.vector_store.ntotal,
                "bm25_documents": self.c.bm25.size,
                "embedding_model": self.c.embedder.model_name,
                "embedding_dim": self.c.embedder.dim if self.c.vector_store.ntotal else None,
                "in_sync": self.c.chunks.count() == self.c.vector_store.ntotal,
            },
            "queries": {
                **query_stats,
                "refusal_rate": round(query_stats["refusals"] / total_queries, 3) if total_queries else 0.0,
                "error_rate": round(query_stats["errors"] / total_queries, 3) if total_queries else 0.0,
            },
            "retrieval": {
                "top_k": self.c.effective_settings.retrieval_top_k,
                "candidate_pool": self.c.effective_settings.retrieval_candidate_pool,
                "rrf_k": self.c.settings.rrf_k,
                "rerank_enabled": self.c.effective_settings.rerank_enabled,
                "rerank_model": self.c.settings.rerank_model
                if self.c.effective_settings.rerank_enabled
                else None,
            },
            "conversations": {"total": self.c.conversations.count()},
            "recent_activity": self.c.query_log.recent(limit=10),
            "evaluation": {"latest": self._latest_eval()},
            "metrics": metrics.snapshot(),
        }

    def _latest_eval(self) -> dict[str, Any] | None:
        runs = self.c.evals.list_runs(limit=1)
        if not runs:
            return None
        run = runs[0]
        return {
            "id": run["id"],
            "dataset": run["dataset"],
            "mode": run["mode"],
            "status": run["status"],
            "started_at": run["started_at"],
            "metrics": run["metrics"],
        }
