"""Document lifecycle: upload, list, inspect, re-index, delete, activate/deactivate.

Business logic only — no HTTP types reach this layer, which is why the same service backs the
API, the CLI's `ingest` command, and the corpus seeding script.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.ingestion.pipeline import IngestResult
from app.models import Chunk, DocumentRecord, DocumentStatus

if TYPE_CHECKING:
    from app.container import AppContainer

log = get_logger("documents")

INGESTIBLE_SUFFIXES = (".md", ".txt", ".pdf", ".docx")


class DocumentService:
    def __init__(self, *, container: AppContainer) -> None:
        self.c = container

    # --- create ------------------------------------------------------------
    def upload(
        self, *, filename: str, data: bytes, tenant_id: str = "default", replace: bool = False
    ) -> IngestResult:
        return self.c.ingestion.ingest_bytes(
            filename=filename, data=data, tenant_id=tenant_id, replace_existing=replace
        )

    def ingest_directory(self, directory: Path, *, replace: bool = False) -> dict[str, Any]:
        """Bulk ingest — backs the CLI `ingest --docs` command and corpus seeding.

        Per-document failures are collected rather than aborting the batch: one unreadable
        file should not prevent the rest of a corpus from being indexed.
        """
        directory = Path(directory)
        if not directory.exists() or not directory.is_dir():
            raise NotFoundError(f"Documents directory not found: {directory}")

        paths = sorted(
            p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in INGESTIBLE_SUFFIXES
        )
        if not paths:
            raise ValidationError(
                f"No ingestible files in {directory} (looking for {', '.join(INGESTIBLE_SUFFIXES)})."
            )

        indexed: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        total_chunks = 0

        for path in paths:
            try:
                result = self.upload(filename=path.name, data=path.read_bytes(), replace=replace)
                if result.duplicate_of and not replace:
                    skipped.append(path.name)
                else:
                    indexed.append(path.name)
                    total_chunks += result.chunks
            except Exception as exc:
                failed.append({"file": path.name, "error": str(exc)})
                log.warning("ingest.file_failed", file=path.name, error=str(exc))

        return {
            "documents": len(indexed),
            "document_names": indexed,
            "skipped_duplicates": skipped,
            "failed": failed,
            "chunks": total_chunks,
            "total_chunks_indexed": self.c.chunks.count(),
            "embedding_model": self.c.embedder.model_name,
            "embedding_dim": self.c.embedder.dim,
            "vector_store_dir": str(self.c.settings.index_dir),
        }

    # --- read --------------------------------------------------------------
    def list(
        self,
        *,
        status: str | None = None,
        doc_type: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DocumentRecord]:
        return self.c.documents.list(
            status=status, doc_type=doc_type, search=search, limit=limit, offset=offset
        )

    def get(self, document_id: str) -> DocumentRecord:
        record = self.c.documents.get(document_id)
        if record is None:
            raise NotFoundError(f"Document {document_id} does not exist.")
        return record

    def chunks_for(self, document_id: str, *, limit: int = 100, offset: int = 0) -> list[Chunk]:
        self.get(document_id)  # 404 before returning an empty list
        return self.c.chunks.list_for_document(document_id, limit=limit, offset=offset)

    def sections_for(self, document_id: str) -> list[dict[str, Any]]:
        """Section tree for the document detail page, derived from chunk metadata."""
        chunks = self.c.chunks.list_for_document(document_id, limit=2000)
        sections: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            meta = chunk.metadata
            key = meta.section or "(no section)"
            node = sections.setdefault(
                key, {"section": key, "subsections": [], "chunk_count": 0, "pages": set()}
            )
            node["chunk_count"] += 1
            if meta.subsection and meta.subsection not in node["subsections"]:
                node["subsections"].append(meta.subsection)
            if meta.page_start:
                node["pages"].add(meta.page_start)
        return [
            {
                "section": node["section"],
                "subsections": node["subsections"],
                "chunk_count": node["chunk_count"],
                "pages": sorted(node["pages"]) or None,
            }
            for node in sections.values()
        ]

    def original_bytes(self, document_id: str) -> tuple[bytes, str, str]:
        record = self.get(document_id)
        extension = Path(record.filename).suffix.lower()
        if not self.c.files.exists(record.content_sha256, extension):
            raise NotFoundError("The original file is no longer stored for this document.")
        return self.c.files.read(record.content_sha256, extension), record.filename, record.mime_type

    # --- mutate ------------------------------------------------------------
    def reindex(self, document_id: str) -> IngestResult:
        record = self.get(document_id)
        if record.status == "processing":
            raise ConflictError("This document is already being processed.")
        return self.c.ingestion.reindex_document(document_id)

    def delete(self, document_id: str, *, purge_original: bool = False) -> int:
        return self.c.ingestion.delete_document(document_id, purge_original=purge_original)

    def set_status(self, document_id: str, status: DocumentStatus) -> DocumentRecord:
        """Activate or deactivate. A deactivated document stays inspectable but is excluded
        from retrieval — the honest way to supersede a policy without destroying the audit
        trail that references it."""
        if status not in ("indexed", "inactive"):
            raise ValidationError(
                "Only 'indexed' (active) and 'inactive' can be set directly.", received=status
            )
        record = self.get(document_id)
        if record.status == "failed":
            raise ConflictError("A failed document must be re-indexed, not activated.")
        self.c.documents.update_status(document_id, status)
        return self.get(document_id)

    def update_metadata(self, document_id: str, **fields: Any) -> DocumentRecord:
        """Metadata correction. Chunk-level copies are refreshed by re-indexing, which the
        caller is told about rather than silently triggered."""
        self.get(document_id)
        self.c.documents.update_metadata(document_id, **fields)
        return self.get(document_id)
