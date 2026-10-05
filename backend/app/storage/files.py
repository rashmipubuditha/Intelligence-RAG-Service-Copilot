"""Content-addressed upload storage.

Files are stored under their SHA-256 digest, never under a user-supplied filename. This
gives three things at once: path-traversal is impossible (we never use client input to build
a path), identical uploads deduplicate for free, and the original filename remains pure
metadata in the registry.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SAFE_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_extension(filename: str) -> str:
    """Extension of the original filename, lowercased, allowlist-checked by the caller."""
    ext = Path(filename).suffix.lower()
    return ext if ext in SAFE_EXTENSIONS else ""


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str, extension: str) -> Path:
        shard = self.root / digest[:2]
        return shard / f"{digest}{extension}"

    def save(self, data: bytes, extension: str) -> tuple[str, Path]:
        digest = sha256_bytes(data)
        target = self.path_for(digest, extension)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        return digest, target

    def read(self, digest: str, extension: str) -> bytes:
        return self.path_for(digest, extension).read_bytes()

    def exists(self, digest: str, extension: str) -> bool:
        return self.path_for(digest, extension).exists()

    def delete(self, digest: str, extension: str) -> None:
        target = self.path_for(digest, extension)
        if target.exists():
            target.unlink()
