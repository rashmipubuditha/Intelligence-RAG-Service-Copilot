"""Cross-cutting HTTP concerns in one place.

Request id, timing, structured access logging, security headers, and a single exception
handler that guarantees **every** error response has the same shape and carries a request id.
That last property is what makes a user-reported problem traceable: they quote the id, and
one grep finds every log line for that request.
"""

from __future__ import annotations

import time
import uuid

from app.core.errors import AppError, RateLimitError
from app.core.logging import bind_request_context, clear_request_context, get_logger
from app.models import utc_now_iso
from app.observability.metrics import metrics
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

log = get_logger("http")

REQUEST_ID_HEADER = "X-Request-ID"


def _error_response(
    status_code: int, code: str, message: str, details: dict, request_id: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
                "timestamp": utc_now_iso(),
            }
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds it to the logging context, times the request."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        clear_request_context()
        bind_request_context(request_id=request_id, path=request.url.path, method=request.method)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log.error("http.unhandled", duration_ms=duration_ms, exc_info=True)
            metrics.increment("http_requests_total", method=request.method, status="500")
            clear_request_context()
            return _error_response(500, "internal_error", "An unexpected error occurred.", {}, request_id)

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"total;dur={duration_ms}"

        metrics.increment("http_requests_total", method=request.method, status=str(response.status_code))
        metrics.observe("http_request_duration", duration_ms, method=request.method)

        # /api/metrics and health are polled; logging them would drown the signal.
        if not request.url.path.endswith(("/metrics", "/health", "/health/ready")):
            log.info("http.request", status=response.status_code, duration_ms=duration_ms)
        clear_request_context()
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers. TLS/HSTS is assumed terminated at the proxy.

    Framing is denied unless `frame_ancestors` names the origins allowed to embed the UI
    (a host that shows the app inside its own page, such as a Hugging Face Space).
    """

    def __init__(self, app, frame_ancestors: str | None = None) -> None:
        super().__init__(app)
        self.frame_ancestors = frame_ancestors

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if self.frame_ancestors:
            response.headers.setdefault(
                "Content-Security-Policy", f"frame-ancestors 'self' {self.frame_ancestors}"
            )
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        # Expected, caller-caused failures are warnings; 5xx are errors.
        logger = log.warning if exc.status_code < 500 else log.error
        logger("http.app_error", code=exc.code, status=exc.status_code, detail=exc.message)
        metrics.increment("app_errors_total", code=exc.code)
        response = _error_response(exc.status_code, exc.code, exc.message, exc.details, request_id)
        if isinstance(exc, RateLimitError):
            response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        problems = [
            {"field": ".".join(str(p) for p in err.get("loc", [])[1:]), "problem": err.get("msg")}
            for err in exc.errors()[:10]
        ]
        return _error_response(
            422,
            "validation_error",
            "The request body or parameters were not valid.",
            {"problems": problems},
            request_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}
        return _error_response(
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            str(exc.detail),
            {},
            request_id,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Internal details are logged, never returned."""
        request_id = getattr(request.state, "request_id", "")
        log.error("http.unexpected", error=str(exc), exc_info=True)
        metrics.increment("app_errors_total", code="internal_error")
        return _error_response(500, "internal_error", "An unexpected error occurred.", {}, request_id)
