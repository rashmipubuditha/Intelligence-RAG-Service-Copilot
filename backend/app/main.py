"""FastAPI application factory.

    uvicorn app.main:app --reload        (from the backend/ directory)
    python main.py serve                 (from the project root)

The lifespan builds the object graph once — embedder, reranker, FAISS index, BM25 index,
SQLite connection — and reconciles any drift between the registry and the indices before
accepting traffic. That startup cost replaces the per-invocation model load that dominated
v1's CLI latency.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from app.api.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    register_exception_handlers,
)
from app.api.routers import chat, conversations, documents, evaluation, system
from app.container import AppContainer
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import RateLimiter
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = get_logger("app")

DESCRIPTION = """
Grounded, citation-backed answers over a firm's own AML/KYC compliance documents.

**What makes the answers trustworthy**

* **Citations cannot be fabricated.** The model emits references into a set the server
  controls; the server resolves them against the passages actually retrieved and discards
  anything else. A citation can only ever point at real indexed text.
* **Refusal is enforced in code, not requested in a prompt.** When no retrieved passage
  clears the evidence floor, no answer is requested from the model at all.
* **Conflicting policy versions are surfaced, not silently resolved.**
* **Evidence strength is reported as retrieval signals plus a banded rule** — never as an
  LLM-generated confidence percentage, which would be uncalibrated.
* **Retrieval quality is measured**, not asserted: see the evaluation endpoints.

Hybrid retrieval (dense BGE embeddings + BM25, fused with Reciprocal Rank Fusion, optional
cross-encoder reranking) over section-aware chunks carrying full document provenance.
"""


def create_app(settings: Settings | None = None, *, warm_models: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = AppContainer(settings)
        app.state.container = container
        app.state.rate_limiter = RateLimiter()
        try:
            info = container.startup(warm_models=warm_models)
            log.info(
                "app.started",
                documents=info.get("documents"),
                chunks=info.get("chunks"),
                provider=settings.llm_provider,
                model=settings.active_model_name,
                embedding_model=settings.embedding_model,
                rerank_enabled=settings.rerank_enabled,
                auth=settings.auth_enabled,
            )
        except Exception as exc:
            # Starting with a broken index is worse than failing to start: the readiness
            # endpoint would report healthy while every query returned nonsense.
            log.error("app.startup_failed", error=str(exc), exc_info=True)
            raise
        try:
            yield
        finally:
            container.shutdown()
            log.info("app.stopped")

    app = FastAPI(
        title="Compliance Intelligence Copilot API",
        description=DESCRIPTION,
        version=system.API_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Compliance Intelligence Copilot"},
    )

    # Order matters: security headers outermost, then request context so that even a
    # failure inside CORS handling still carries a request id.
    app.add_middleware(SecurityHeadersMiddleware, frame_ancestors=settings.frame_ancestors)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Server-Timing", "Retry-After"],
    )

    register_exception_handlers(app)

    for router in (system.router, chat.router, documents.router, conversations.router, evaluation.router):
        app.include_router(router, prefix="/api")

    if settings.static_dir and (settings.static_dir / "index.html").is_file():
        _serve_spa(app, settings.static_dir.resolve())
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, str]:
            return {
                "name": "Compliance Intelligence Copilot API",
                "version": system.API_VERSION,
                "docs": "/docs",
                "health": "/api/health",
            }

    return app


def _serve_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend from this process — the single-container equivalent of
    frontend/nginx.conf. Registered last, so every API and docs route takes precedence."""
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        # An unknown API path must stay a JSON 404, not turn into the app shell.
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir):
            # Hashed build assets are immutable, so they can be cached hard.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if path.startswith("assets/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        # Client-side routes such as /documents/doc_abc resolve to the app shell, which must
        # never be cached or a deploy leaves clients on asset hashes that no longer exist.
        return FileResponse(index, headers={"Cache-Control": "no-store, must-revalidate"})


app = create_app()
