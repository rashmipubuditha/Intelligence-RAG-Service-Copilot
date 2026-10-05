"""Composition root.

One place builds the object graph, and both consumers use it: the FastAPI lifespan and the
CLI. That matters more than it sounds — it is why `python main.py query` and `POST /api/chat`
execute the *same* retrieval and generation code, and why the evaluation harness measures
production behaviour rather than a parallel implementation of it.

Heavy objects (embedder, reranker, FAISS index, BM25 index, SQLite connection) are created
once per process. In v1 each CLI invocation reloaded the embedding model, which was ~2–3 s of
the ~22 s end-to-end latency; under the server that cost is paid once at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.ingestion.pipeline import IngestionPipeline
from app.rag.embedder import Embedder, get_embedder
from app.rag.llm import LLMProvider, build_provider
from app.rag.pipeline import RagPipeline
from app.rag.reranker import Reranker, build_reranker
from app.rag.retrieval import HybridRetriever
from app.storage.bm25_store import BM25Store
from app.storage.db import Database
from app.storage.files import FileStore
from app.storage.repositories import (
    ChunkRepository,
    ConversationRepository,
    DocumentRepository,
    EvalRepository,
    QueryLogRepository,
)
from app.storage.vector_store import VectorStore

log = get_logger("container")


@dataclass
class RuntimeOverrides:
    """Session-scoped settings overrides from the Settings page.

    Never persisted to disk: a demo UI must be able to try a different model without
    rewriting the deployment's configuration.
    """

    llm_provider: str | None = None
    llm_model: str | None = None
    top_k: int | None = None
    rerank_enabled: bool | None = None
    temperature: float | None = None

    def apply(self, settings: Settings) -> Settings:
        updates = {}
        if self.llm_provider:
            updates["llm_provider"] = self.llm_provider
        if self.top_k:
            updates["retrieval_top_k"] = self.top_k
        if self.rerank_enabled is not None:
            updates["rerank_enabled"] = self.rerank_enabled
        if self.temperature is not None:
            updates["llm_temperature"] = self.temperature
        if self.llm_model:
            key = "groq_model" if (self.llm_provider or settings.llm_provider) == "groq" else "ollama_model"
            updates[key] = self.llm_model
        return settings.model_copy(update=updates) if updates else settings


class AppContainer:
    """Lazily builds and holds the application's singletons."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.overrides = RuntimeOverrides()

    # --- storage -----------------------------------------------------------
    @cached_property
    def db(self) -> Database:
        return Database(self.settings.db_path)

    @cached_property
    def documents(self) -> DocumentRepository:
        return DocumentRepository(self.db)

    @cached_property
    def chunks(self) -> ChunkRepository:
        return ChunkRepository(self.db)

    @cached_property
    def conversations(self) -> ConversationRepository:
        return ConversationRepository(self.db)

    @cached_property
    def evals(self) -> EvalRepository:
        return EvalRepository(self.db)

    @cached_property
    def query_log(self) -> QueryLogRepository:
        return QueryLogRepository(self.db)

    @cached_property
    def files(self) -> FileStore:
        return FileStore(self.settings.uploads_dir)

    # --- models ------------------------------------------------------------
    @cached_property
    def embedder(self) -> Embedder:
        return get_embedder(
            self.settings.embedding_model,
            query_prefix=self.settings.embedding_query_prefix,
            batch_size=self.settings.embedding_batch_size,
        )

    @cached_property
    def reranker(self) -> Reranker:
        return build_reranker(
            enabled=self.effective_settings.rerank_enabled,
            model_name=self.settings.rerank_model,
            top_n=self.settings.rerank_top_n,
        )

    # --- indices -----------------------------------------------------------
    @cached_property
    def vector_store(self) -> VectorStore:
        return VectorStore.load_or_create(
            self.settings.index_dir, dim=self.embedder.dim, embedding_model=self.embedder.model_name
        )

    @cached_property
    def bm25(self) -> BM25Store:
        return BM25Store.load_or_create(self.settings.index_dir)

    # --- pipelines ---------------------------------------------------------
    @property
    def effective_settings(self) -> Settings:
        return self.overrides.apply(self.settings)

    def provider_factory(self) -> LLMProvider:
        settings = self.effective_settings
        return build_provider(settings, provider=self.overrides.llm_provider, model=self.overrides.llm_model)

    @property
    def retriever(self) -> HybridRetriever:
        """Rebuilt per access so a settings override (top-k, reranking) takes effect
        immediately; the expensive members it composes are all cached singletons."""
        return HybridRetriever(
            settings=self.effective_settings,
            vector_store=self.vector_store,
            bm25=self.bm25,
            chunks=self.chunks,
            embedder=self.embedder,
            reranker=self.reranker,
        )

    @property
    def rag(self) -> RagPipeline:
        return RagPipeline(
            settings=self.effective_settings,
            retriever=self.retriever,
            provider_factory=self.provider_factory,
        )

    @cached_property
    def ingestion(self) -> IngestionPipeline:
        return IngestionPipeline(
            settings=self.settings,
            documents=self.documents,
            chunks=self.chunks,
            vector_store=self.vector_store,
            bm25=self.bm25,
            files=self.files,
            embedder=self.embedder,
        )

    # --- services ----------------------------------------------------------
    @cached_property
    def document_service(self):
        from app.services.document_service import DocumentService

        return DocumentService(container=self)

    @cached_property
    def chat_service(self):
        from app.services.chat_service import ChatService

        return ChatService(container=self)

    @cached_property
    def stats_service(self):
        from app.services.stats_service import StatsService

        return StatsService(container=self)

    @cached_property
    def evaluation_service(self):
        from app.services.evaluation_service import EvaluationService

        return EvaluationService(container=self)

    # --- lifecycle ---------------------------------------------------------
    def startup(self, *, warm_models: bool = True) -> dict[str, object]:
        """Open the database, load indices, reconcile drift, warm the models."""
        info: dict[str, object] = {}
        if warm_models:
            self.embedder.warm_up()
            if getattr(self.reranker, "enabled", False):
                try:
                    self.reranker.warm_up()  # type: ignore[union-attr]
                except Exception as exc:
                    log.warning("reranker.warmup_failed", error=str(exc))
        info["chunks"] = self.chunks.count()
        info["documents"] = self.documents.count()
        info["reconciliation"] = self.ingestion.reconcile()
        log.info("startup.ready", **{k: v for k, v in info.items() if k != "reconciliation"})
        return info

    def shutdown(self) -> None:
        try:
            self.ingestion.persist_indices()
        finally:
            self.db.close()


_container: AppContainer | None = None


def get_container(settings: Settings | None = None) -> AppContainer:
    global _container
    if _container is None:
        _container = AppContainer(settings)
    return _container


def reset_container() -> None:
    """Test hook — drops the process-wide container so a test can build its own."""
    global _container
    _container = None
