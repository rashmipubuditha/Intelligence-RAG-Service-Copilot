"""The ingestion pipeline: bytes in, indexed document out.

Nine stages, each individually testable:

    validate → store original → extract → clean → metadata → chunk
             → injection scan → embed → index (FAISS + BM25) → registry

Failure semantics: a document is either fully indexed or not indexed. Any stage that fails
marks the registry row `failed` with a reason and leaves the indices untouched; a partially
ingested document never becomes retrievable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import AppError, ExtractionError
from app.core.logging import get_logger
from app.ingestion.chunking import chunk_document
from app.ingestion.cleaning import clean_text
from app.ingestion.extractors import extract
from app.ingestion.injection import scan_for_injection
from app.ingestion.metadata import extract_metadata
from app.ingestion.validators import validate_upload
from app.models import Chunk, DocumentRecord, utc_now_iso
from app.rag.embedder import Embedder
from app.storage.bm25_store import BM25Store
from app.storage.files import FileStore
from app.storage.repositories import ChunkRepository, DocumentRepository, new_id
from app.storage.vector_store import VectorStore

log = get_logger("ingestion")


@dataclass
class IngestResult:
    document: DocumentRecord
    chunks: int
    duplicate_of: str | None = None
    elapsed_ms: int = 0


class IngestionPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        vector_store: VectorStore,
        bm25: BM25Store,
        files: FileStore,
        embedder: Embedder,
    ) -> None:
        self.settings = settings
        self.documents = documents
        self.chunks = chunks
        self.vector_store = vector_store
        self.bm25 = bm25
        self.files = files
        self.embedder = embedder

    # ------------------------------------------------------------------
    def ingest_bytes(
        self,
        *,
        filename: str,
        data: bytes,
        tenant_id: str = "default",
        replace_existing: bool = False,
    ) -> IngestResult:
        started = time.perf_counter()

        # 1. validate (raises before anything is persisted)
        safe_name, extension, mime_type = validate_upload(filename, data, self.settings.max_upload_bytes)

        # 2. store the original, content-addressed (dedup falls out of this for free)
        digest, _path = self.files.save(data, extension)
        existing = self.documents.get_by_hash(digest)
        if existing and not replace_existing:
            log.info("ingest.duplicate", document_id=existing.id, filename=safe_name)
            return IngestResult(
                document=existing,
                chunks=existing.chunk_count,
                duplicate_of=existing.id,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        if existing and replace_existing:
            self.delete_document(existing.id, purge_original=False)

        document_id = new_id("doc")
        record = DocumentRecord(
            id=document_id,
            filename=safe_name,
            title=safe_name,
            status="processing",
            content_sha256=digest,
            byte_size=len(data),
            mime_type=mime_type,
            uploaded_at=utc_now_iso(),
            tenant_id=tenant_id,
        )
        self.documents.create(record)

        try:
            return self._process(record, data, extension, started)
        except AppError as exc:
            self.documents.update_status(document_id, "failed", failure_reason=exc.message)
            log.warning("ingest.failed", document_id=document_id, code=exc.code, reason=exc.message)
            raise
        except Exception as exc:  # unexpected: still leave a diagnosable registry row
            self.documents.update_status(document_id, "failed", failure_reason=str(exc)[:500])
            log.error("ingest.error", document_id=document_id, error=str(exc), exc_info=True)
            raise

    # ------------------------------------------------------------------
    def _process(self, record: DocumentRecord, data: bytes, extension: str, started: float) -> IngestResult:
        # 3. extract
        extracted = extract(data, extension, self.settings.max_pdf_pages)

        # 4. clean
        cleaned = clean_text(extracted.text, is_pdf=(extension == ".pdf"))
        if not cleaned.strip():
            raise ExtractionError("The document contained no text after cleaning.")

        # 5. metadata
        meta = extract_metadata(cleaned, record.filename)
        self.documents.update_metadata(
            record.id,
            title=meta.title,
            doc_type=meta.doc_type,
            version=meta.version,
            effective_date=meta.effective_date,
            publication_date=meta.publication_date,
            owner=meta.owner,
            review_cycle=meta.review_cycle,
            family_key=meta.family_key,
        )

        # 6. chunk
        chunks = chunk_document(
            document_id=record.id,
            filename=record.filename,
            extracted=extracted,
            cleaned_text=cleaned,
            metadata=meta,
            starting_faiss_id=self.chunks.next_faiss_id(),
        )
        if not chunks:
            raise ExtractionError("The document produced no chunks.")

        # 7. injection scan (flag for a human; does not block ingestion)
        flags = scan_for_injection(cleaned)

        # 8. embed + index
        embeddings = self.embedder.encode_passages([c.text for c in chunks])
        self.vector_store.add(embeddings, [c.faiss_id for c in chunks])
        self.bm25.add_many([(c.faiss_id, c.text) for c in chunks])

        # 9. commit: chunks first, then mark the document indexed. A crash between the two
        # leaves orphan vectors, which startup reconciliation removes — never a citation
        # pointing at missing text.
        self.chunks.add_many(chunks)
        self.persist_indices()
        self.documents.update_status(
            record.id,
            "indexed",
            chunk_count=len(chunks),
            indexed=True,
            embedding_model=self.embedder.model_name,
            injection_flags=flags,
            page_count=extracted.page_count,
            failure_reason=None,
        )

        updated = self.documents.get(record.id)
        assert updated is not None
        elapsed = int((time.perf_counter() - started) * 1000)
        log.info(
            "ingest.indexed",
            document_id=record.id,
            title=meta.title,
            version=meta.version,
            chunks=len(chunks),
            flags=len(flags),
            elapsed_ms=elapsed,
        )
        return IngestResult(document=updated, chunks=len(chunks), elapsed_ms=elapsed)

    # ------------------------------------------------------------------
    def reindex_document(self, document_id: str) -> IngestResult:
        """Re-run the pipeline over the stored original — needed after a chunking or
        embedding change. Idempotent: the same document produces the same chunk uids."""
        record = self.documents.get(document_id)
        if record is None:
            from app.core.errors import NotFoundError

            raise NotFoundError(f"Document {document_id} does not exist.")

        extension = f".{record.filename.rsplit('.', 1)[-1].lower()}"
        data = self.files.read(record.content_sha256, extension)

        removed = self.chunks.delete_for_document(document_id)
        self.vector_store.remove(removed)
        self.bm25.remove(set(removed))
        self.documents.update_status(document_id, "processing", failure_reason=None)

        started = time.perf_counter()
        try:
            return self._process(record, data, extension, started)
        except AppError as exc:
            self.documents.update_status(document_id, "failed", failure_reason=exc.message)
            raise

    def delete_document(self, document_id: str, *, purge_original: bool = False) -> int:
        """Remove a document's chunks from both indices, then the registry row.

        Order matters: registry-visible state is removed before vectors, so a crash can only
        ever leave unreferenced vectors (which reconciliation cleans), never a dangling
        citation.
        """
        record = self.documents.get(document_id)
        if record is None:
            from app.core.errors import NotFoundError

            raise NotFoundError(f"Document {document_id} does not exist.")

        faiss_ids = self.chunks.delete_for_document(document_id)
        self.documents.delete(document_id)
        self.vector_store.remove(faiss_ids)
        self.bm25.remove(set(faiss_ids))
        self.persist_indices()

        if purge_original:
            extension = f".{record.filename.rsplit('.', 1)[-1].lower()}"
            still_used = self.documents.get_by_hash(record.content_sha256)
            if still_used is None:
                self.files.delete(record.content_sha256, extension)

        log.info("document.deleted", document_id=document_id, chunks=len(faiss_ids))
        return len(faiss_ids)

    # ------------------------------------------------------------------
    def persist_indices(self) -> None:
        self.vector_store.persist(self.settings.index_dir)
        self.bm25.persist(self.settings.index_dir)

    def reconcile(self) -> dict[str, int]:
        """Drop vectors with no chunk row, and rebuild BM25 from the registry.

        Runs at startup. The registry is the source of truth; the indices are derived.
        """
        known = set(self.chunks.all_faiss_ids())
        orphans: list[int] = []
        # IndexIDMap2 exposes its id map; anything not in the registry is an orphan.
        try:
            id_map = self.vector_store.index.id_map
            indexed_ids = {int(id_map.at(i)) for i in range(id_map.size())}
        except Exception:
            indexed_ids = set()
        orphans = sorted(indexed_ids - known)
        if orphans:
            self.vector_store.remove(orphans)
            log.warning("reconcile.orphans_removed", count=len(orphans))

        missing = sorted(known - indexed_ids) if indexed_ids else []
        if self.bm25.size != len(known):
            self.bm25.reset()
            self.bm25.add_many([(c.faiss_id, c.text) for c in self.chunks.all_chunks()])
            log.info("reconcile.bm25_rebuilt", count=self.bm25.size)
        if orphans or self.bm25.size != len(known):
            self.persist_indices()
        return {
            "chunks_in_registry": len(known),
            "vectors_in_index": self.vector_store.ntotal,
            "orphans_removed": len(orphans),
            "missing_vectors": len(missing),
        }

    def rebuild_all(self) -> dict[str, int]:
        """Full rebuild of both indices from the registry — the documented recovery path."""
        all_chunks: list[Chunk] = self.chunks.all_chunks()
        self.vector_store.reset()
        self.bm25.reset()
        if all_chunks:
            embeddings = self.embedder.encode_passages([c.text for c in all_chunks])
            self.vector_store.add(embeddings, [c.faiss_id for c in all_chunks])
            self.bm25.add_many([(c.faiss_id, c.text) for c in all_chunks])
        self.persist_indices()
        log.info("index.rebuilt", chunks=len(all_chunks))
        return {"chunks": len(all_chunks), "vectors": self.vector_store.ntotal}
