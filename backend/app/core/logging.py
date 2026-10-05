"""Structured logging.

Replaces the ad-hoc `print(..., file=sys.stderr)` calls of the original implementation.
structlog's context-local binding means a request id bound once in middleware appears on
every subsequent log line for that request, including lines emitted deep inside the RAG
pipeline, without threading an argument through every function.

Privacy: question text is NOT logged by default (LOG_QUESTIONS=false). Full question text
and retrieved context live in audit.log, which is local, append-only, and exists precisely
for that purpose. Application logs carry a question hash so a log line can still be
correlated with an audit entry without exporting compliance content to a log aggregator.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Any

import structlog

_SECRET_HINTS = ("api_key", "apikey", "authorization", "token", "secret", "password", "gsk_")


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    for noisy in ("httpx", "httpcore", "sentence_transformers", "transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_secrets,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def _redact_secrets(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Drop anything secret-shaped before it can reach a log sink."""
    for key, value in list(event_dict.items()):
        lowered = key.lower()
        if any(hint in lowered for hint in _SECRET_HINTS) or (isinstance(value, str) and "gsk_" in value):
            event_dict[key] = "[redacted]"
    return event_dict


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def hash_text(text: str) -> str:
    """Stable short hash, used to reference a question in logs without storing it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def bind_request_context(**kwargs: Any) -> None:
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
