"""Chat endpoints: one non-streaming, one SSE.

Both call the same service and therefore the same retrieval and guardrails — the streaming
endpoint is a different transport, not a different pipeline.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.api.deps import ContainerDep, RateLimiterDep, RequireRead, rate_limit_bucket
from app.api.schemas import ChatRequest, ChatResponse, ErrorResponse
from app.core.logging import get_logger
from app.models import RetrievalFilters
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

router = APIRouter(prefix="/chat", tags=["chat"])
log = get_logger("api.chat")


def _filters_from(request: ChatRequest) -> RetrievalFilters | None:
    if request.filters is None:
        return None
    return RetrievalFilters(**request.filters.model_dump())


@router.post(
    "",
    response_model=ChatResponse,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "Nothing is indexed yet."},
    },
    summary="Ask a compliance question (non-streaming)",
    description=(
        "Returns a grounded answer with citations resolved against the retrieved passages, an "
        "evidence band derived from retrieval signals, and any version conflicts found. "
        "A superset of the v1 CLI response shape."
    ),
)
async def chat(
    body: ChatRequest,
    request: Request,
    container: ContainerDep,
    caller: RequireRead,
    limiter: RateLimiterDep,
) -> ChatResponse:
    limiter.check(rate_limit_bucket(request, caller, "chat"), container.settings.rate_limit_per_minute)
    request_id = getattr(request.state, "request_id", None)

    # Retrieval and generation are blocking (CPU-bound encode + network LLM call), so they run
    # off the event loop to keep the server responsive under concurrent requests.
    conversation_id, result = await run_in_threadpool(
        container.chat_service.ask,
        body.question,
        conversation_id=body.conversation_id,
        filters=_filters_from(body),
        k=body.k,
        request_id=request_id,
        use_history=body.use_history,
    )

    return ChatResponse(
        question=result.question,
        rewritten_question=result.rewritten_question,
        answer=result.answer,
        citations=result.citations,
        evidence=result.evidence,
        conflicts=result.conflicts,
        refused=result.refused,
        model=result.model,
        conversation_id=conversation_id,
        latency_ms=result.timings.total_ms,
        timings=result.timings,
        token_usage=result.token_usage,
        retrieval=result.retrieval_params.model_dump(mode="json") if result.retrieval_params else {},
        request_id=request_id,
        timestamp=result.timestamp,
        error=result.error,
    )


@router.post(
    "/stream",
    summary="Ask a compliance question (SSE stream)",
    description=(
        "Server-sent events in a fixed order: `conversation` → `meta` → `retrieval` → "
        "`token`* → `citations` → `evidence` → (`conflicts`) → `done`. An `error` event "
        "replaces whatever would have followed. Citation markers emitted by the model are "
        "resolved server-side against the retrieved set, so the `citations` event can only "
        "ever contain real passages."
    ),
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_stream(
    body: ChatRequest,
    request: Request,
    container: ContainerDep,
    caller: RequireRead,
    limiter: RateLimiterDep,
) -> StreamingResponse:
    limiter.check(rate_limit_bucket(request, caller, "chat"), container.settings.rate_limit_per_minute)
    request_id = getattr(request.state, "request_id", None)

    def sync_events():
        return container.chat_service.ask_stream(
            body.question,
            conversation_id=body.conversation_id,
            filters=_filters_from(body),
            k=body.k,
            request_id=request_id,
            use_history=body.use_history,
        )

    async def event_source() -> AsyncIterator[str]:
        try:
            generator = await run_in_threadpool(sync_events)
            async for event in iterate_in_threadpool(generator):
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except Exception as exc:
            # The HTTP status is already 200 by the time streaming starts, so transport
            # failures must be reported inside the stream.
            from app.core.errors import AppError

            code = exc.code if isinstance(exc, AppError) else "internal_error"
            message = exc.message if isinstance(exc, AppError) else "The stream failed."
            log.warning("chat.stream_failed", code=code, error=str(exc))
            yield f"event: error\ndata: {json.dumps({'code': code, 'message': message})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stops nginx buffering the stream
        },
    )
