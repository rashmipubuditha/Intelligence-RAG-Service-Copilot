"""System endpoints: health, readiness, stats, settings, metrics."""

from __future__ import annotations

from typing import Any

from app.api.deps import ContainerDep, RequireRead, RequireWrite
from app.api.schemas import (
    HealthResponse,
    ReadinessCheck,
    ReadinessResponse,
    SettingsPatchRequest,
    SettingsResponse,
    StatsResponse,
)
from app.core.logging import get_logger
from app.ingestion.validators import ALLOWED_EXTENSIONS
from app.observability.metrics import metrics
from fastapi import APIRouter, Response

router = APIRouter(tags=["system"])
log = get_logger("api.system")

API_VERSION = "0.2.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health() -> HealthResponse:
    """Always 200 while the process is serving. Deliberately checks nothing else — a liveness
    probe that fails on a dependency outage causes restarts that do not fix anything."""
    return HealthResponse(version=API_VERSION)


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
async def readiness(container: ContainerDep) -> ReadinessResponse:
    """Reports whether the service can actually answer a question right now."""
    checks: list[ReadinessCheck] = []

    try:
        chunk_count = container.chunks.count()
        checks.append(ReadinessCheck(name="database", ok=True, detail=f"sqlite ok ({chunk_count} chunks)"))
    except Exception as exc:
        checks.append(ReadinessCheck(name="database", ok=False, detail=str(exc)))
        chunk_count = 0

    vectors = container.vector_store.ntotal
    checks.append(
        ReadinessCheck(
            name="index",
            ok=vectors > 0,
            detail=f"{vectors} vectors, {container.bm25.size} bm25 docs"
            if vectors
            else "empty — ingest a document first",
        )
    )
    checks.append(
        ReadinessCheck(
            name="index_consistency",
            ok=vectors == chunk_count,
            detail=f"registry {chunk_count} vs index {vectors}",
        )
    )

    try:
        provider = container.provider_factory()
        reachable, detail = provider.health()
        checks.append(ReadinessCheck(name="llm_provider", ok=reachable, detail=detail))
    except Exception as exc:
        checks.append(ReadinessCheck(name="llm_provider", ok=False, detail=str(exc)))

    settings = container.settings
    checks.append(
        ReadinessCheck(
            name="auth",
            ok=True,
            detail="public read-only; api key required for writes"
            if settings.public_read
            else "api key required"
            if settings.auth_enabled
            else "open (no API_KEY configured — local development default)",
        )
    )

    return ReadinessResponse(ready=all(c.ok for c in checks[:3]), checks=checks)


@router.get("/stats", response_model=StatsResponse, summary="Dashboard aggregates")
async def stats(container: ContainerDep, caller: RequireRead) -> StatsResponse:
    """Every figure here is measured from the registry, the query log, and the indices.
    Unknown values are reported as zero or null rather than invented."""
    return StatsResponse.model_validate(container.stats_service.dashboard())


@router.get("/metrics", summary="Prometheus metrics", response_class=Response)
async def prometheus_metrics() -> Response:
    return Response(content=metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/settings", response_model=SettingsResponse, summary="Effective runtime settings")
async def get_settings_route(container: ContainerDep, caller: RequireRead) -> SettingsResponse:
    """Secrets are never returned — only whether they are configured."""
    settings = container.settings
    effective = container.effective_settings
    return SettingsResponse(
        llm_provider=effective.llm_provider,
        llm_model=effective.active_model_name,
        groq_configured=bool(settings.groq_api_key),
        ollama_base_url=settings.ollama_base_url,
        embedding_model=settings.embedding_model,
        embedding_query_prefix_enabled=bool(settings.embedding_query_prefix),
        retrieval_top_k=effective.retrieval_top_k,
        retrieval_candidate_pool=effective.retrieval_candidate_pool,
        rrf_k=settings.rrf_k,
        rerank_enabled=effective.rerank_enabled,
        rerank_model=settings.rerank_model,
        temperature=effective.llm_temperature,
        context_max_tokens=settings.context_max_tokens,
        evidence_floors={
            "refusal": settings.evidence_refusal_floor,
            "moderate": settings.evidence_moderate_floor,
            "strong": settings.evidence_strong_floor,
        },
        auth_enabled=settings.auth_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        max_upload_mb=round(settings.max_upload_bytes / 1_048_576, 1),
        allowed_file_types=sorted(ALLOWED_EXTENSIONS),
    )


@router.patch(
    "/settings",
    response_model=SettingsResponse,
    summary="Apply session-scoped setting overrides",
    description=(
        "Overrides live in process memory only and are never written to disk, so a demo can "
        "try a different model or retrieval configuration without altering the deployment's "
        "configuration. Enabling reranking loads the cross-encoder on first use."
    ),
)
async def patch_settings(
    body: SettingsPatchRequest, container: ContainerDep, caller: RequireWrite
) -> SettingsResponse:
    overrides = container.overrides
    changed: dict[str, Any] = {}

    if body.llm_provider is not None:
        overrides.llm_provider = body.llm_provider
        changed["llm_provider"] = body.llm_provider
    if body.llm_model is not None:
        overrides.llm_model = body.llm_model
        changed["llm_model"] = body.llm_model
    if body.top_k is not None:
        overrides.top_k = body.top_k
        changed["top_k"] = body.top_k
    if body.temperature is not None:
        overrides.temperature = body.temperature
        changed["temperature"] = body.temperature
    if body.rerank_enabled is not None and body.rerank_enabled != overrides.rerank_enabled:
        overrides.rerank_enabled = body.rerank_enabled
        changed["rerank_enabled"] = body.rerank_enabled
        # The reranker is a cached singleton keyed on the enabled flag; drop it so the next
        # request builds the right one.
        container.__dict__.pop("reranker", None)

    if changed:
        log.info("settings.overridden", **changed)
    return await get_settings_route(container, caller)
