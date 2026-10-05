"""One error hierarchy for the whole application.

Every failure the user can cause maps to an AppError subclass carrying a stable machine
code and an HTTP status. The API's exception handler turns these into a uniform response
envelope; the CLI turns them into the structured JSON error field. Internal details stay
in logs — never in a response body.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class. `code` is a stable identifier clients may branch on."""

    code: str = "internal_error"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details: dict[str, Any] = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(AppError):
    code = "validation_error"
    status_code = 422
    message = "The request was not valid."


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource does not exist."


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "The resource is in a conflicting state."


class UnsupportedFileError(AppError):
    code = "unsupported_file_type"
    status_code = 422
    message = "This file type is not accepted."


class FileTooLargeError(AppError):
    code = "file_too_large"
    status_code = 413
    message = "The uploaded file exceeds the size limit."


class ExtractionError(AppError):
    code = "extraction_failed"
    status_code = 422
    message = "No readable text could be extracted from the document."


class IndexNotReadyError(AppError):
    code = "index_not_ready"
    status_code = 503
    message = "No documents are indexed yet. Upload a document or run ingest first."


class LLMError(AppError):
    code = "llm_unavailable"
    status_code = 502
    message = "The language model could not be reached or returned an unusable response."


class AuthError(AppError):
    code = "unauthorized"
    status_code = 401
    message = "A valid API key is required for this operation."


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = 403
    message = "This API key does not have permission for this operation."


class RateLimitError(AppError):
    code = "rate_limited"
    status_code = 429
    message = "Too many requests. Please retry shortly."

    def __init__(self, message: str | None = None, retry_after: int = 60, **details: Any):
        super().__init__(message, retry_after=retry_after, **details)
        self.retry_after = retry_after
