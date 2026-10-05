"""Upload validation — the trust boundary of the whole system.

Extension checks alone are trivially spoofed, so the declared extension and the actual file
signature must agree. Size is checked before the bytes are parsed, and PDFs have a page cap
so a 20 MB file cannot expand into an unbounded extraction job.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import FileTooLargeError, UnsupportedFileError, ValidationError

ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}

MIME_BY_EXTENSION = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Magic bytes we can assert on. Text formats have no signature, so they are validated by
# decodability instead.
MAGIC_SIGNATURES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",  # docx is a zip container
}

_UNSAFE_NAME = re.compile(r"[\x00-\x1f<>:\"|?*]")


def validate_filename(filename: str) -> str:
    """Return a safe display name. Storage paths never derive from this value."""
    if not filename or not filename.strip():
        raise ValidationError("A filename is required.")
    name = Path(filename).name  # strips any directory component, including traversal
    if name in {".", ".."} or _UNSAFE_NAME.search(name):
        raise ValidationError("The filename contains characters that are not allowed.", filename=filename)
    if len(name) > 255:
        raise ValidationError("The filename is too long.", max_length=255)
    return name


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are accepted.",
            received=ext or "(none)",
        )
    return ext


def validate_size(size: int, max_bytes: int) -> None:
    if size <= 0:
        raise ValidationError("The uploaded file is empty.")
    if size > max_bytes:
        raise FileTooLargeError(
            f"The file is {size / 1_048_576:.1f} MB; the limit is {max_bytes / 1_048_576:.0f} MB.",
            size=size,
            max_bytes=max_bytes,
        )


def validate_magic_bytes(data: bytes, extension: str) -> None:
    """Confirm the content matches the claimed type."""
    signature = MAGIC_SIGNATURES.get(extension)
    if signature is not None:
        if not data.startswith(signature):
            raise UnsupportedFileError(
                f"The file content does not match a {extension} file.", declared_extension=extension
            )
        return
    # Text formats: must decode as UTF-8 (or latin-1 as a tolerated fallback).
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            data.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise UnsupportedFileError(
                "The file is not readable text.", declared_extension=extension
            ) from exc


def validate_upload(filename: str, data: bytes, max_bytes: int) -> tuple[str, str, str]:
    """Run every check. Returns (safe_name, extension, mime_type)."""
    safe_name = validate_filename(filename)
    extension = validate_extension(safe_name)
    validate_size(len(data), max_bytes)
    validate_magic_bytes(data, extension)
    return safe_name, extension, MIME_BY_EXTENSION[extension]
