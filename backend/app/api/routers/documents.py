"""Document management endpoints."""

from __future__ import annotations

from app.api.deps import ContainerDep, RateLimiterDep, RequireRead, RequireWrite, rate_limit_bucket
from app.api.schemas import (
    ChunkListResponse,
    ChunkResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentPatchRequest,
    DocumentResponse,
    ErrorResponse,
    Page,
    SectionNode,
    UploadedDocument,
    UploadFailure,
    UploadResponse,
)
from app.core.errors import FileTooLargeError, ValidationError
from app.core.logging import get_logger
from app.models import Chunk, DocumentRecord
from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/documents", tags=["documents"])
log = get_logger("api.documents")


def _to_response(record: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(**record.model_dump())


def _chunk_to_response(chunk: Chunk) -> ChunkResponse:
    meta = chunk.metadata
    return ChunkResponse(
        chunk_uid=chunk.chunk_uid,
        chunk_index=meta.chunk_index,
        section=meta.section,
        subsection=meta.subsection,
        heading_path=meta.heading_path,
        page_start=meta.page_start,
        page_end=meta.page_end,
        char_count=meta.char_count,
        token_estimate=meta.token_estimate,
        text=chunk.text,
        label=meta.citation_label,
    )


@router.post(
    "",
    response_model=UploadResponse,
    status_code=201,
    summary="Upload and index one or more documents",
    description=(
        "Accepts .md, .txt, .pdf and .docx. Files are validated by extension **and** magic "
        "bytes, size-capped, stored content-addressed, then extracted, cleaned, chunked with "
        "full heading provenance, scanned for injection patterns, embedded, and indexed. "
        "Identical content is deduplicated rather than indexed twice."
    ),
    responses={413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def upload_documents(
    request: Request,
    container: ContainerDep,
    caller: RequireWrite,
    limiter: RateLimiterDep,
    files: list[UploadFile] = File(..., description="One or more policy documents."),
    replace: bool = Query(False, description="Re-index if identical content already exists."),
) -> UploadResponse:
    limiter.check(
        rate_limit_bucket(request, caller, "upload"),
        container.settings.rate_limit_upload_per_minute,
    )
    settings = container.settings
    if len(files) > settings.max_upload_files:
        raise ValidationError(
            f"At most {settings.max_upload_files} files may be uploaded at once.",
            received=len(files),
        )

    uploaded: list[UploadedDocument] = []
    failed: list[UploadFailure] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        # Reject on the declared size before reading the body into memory where possible.
        declared = upload.size
        if declared is not None and declared > settings.max_upload_bytes:
            failed.append(
                UploadFailure(
                    file=filename,
                    code=FileTooLargeError.code,
                    error=f"File is {declared / 1_048_576:.1f} MB; "
                    f"limit is {settings.max_upload_bytes / 1_048_576:.0f} MB.",
                )
            )
            continue
        try:
            data = await upload.read()
            result = await run_in_threadpool(
                container.document_service.upload,
                filename=filename,
                data=data,
                tenant_id=caller.tenant_id,
                replace=replace,
            )
            uploaded.append(
                UploadedDocument(
                    document=_to_response(result.document),
                    chunks=result.chunks,
                    duplicate_of=result.duplicate_of,
                    elapsed_ms=result.elapsed_ms,
                )
            )
        except Exception as exc:
            from app.core.errors import AppError

            code = exc.code if isinstance(exc, AppError) else "ingest_failed"
            message = exc.message if isinstance(exc, AppError) else str(exc)
            failed.append(UploadFailure(file=filename, code=code, error=message))
        finally:
            await upload.close()

    if not uploaded and failed:
        # Nothing succeeded — surface the first failure as the status so clients can branch.
        raise ValidationError(
            "No files could be indexed.",
            failures=[failure.model_dump() for failure in failed],
        )

    return UploadResponse(uploaded=uploaded, failed=failed)


@router.get("", response_model=DocumentListResponse, summary="List documents")
async def list_documents(
    container: ContainerDep,
    caller: RequireRead,
    status: str | None = Query(None, pattern="^(processing|indexed|failed|inactive)$"),
    doc_type: str | None = Query(None),
    q: str | None = Query(None, description="Search title and filename."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DocumentListResponse:
    records = container.document_service.list(
        status=status, doc_type=doc_type, search=q, limit=limit, offset=offset
    )
    return DocumentListResponse(
        documents=[_to_response(r) for r in records],
        page=Page(
            limit=limit,
            offset=offset,
            total=container.documents.count(status=status),
            returned=len(records),
        ),
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Document metadata, section tree, and a chunk preview",
    responses={404: {"model": ErrorResponse}},
)
async def get_document(
    document_id: str, container: ContainerDep, caller: RequireRead
) -> DocumentDetailResponse:
    service = container.document_service
    record = service.get(document_id)
    return DocumentDetailResponse(
        document=_to_response(record),
        sections=[SectionNode(**node) for node in service.sections_for(document_id)],
        chunk_preview=[_chunk_to_response(c) for c in service.chunks_for(document_id, limit=5)],
    )


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkListResponse,
    summary="Indexed chunks for a document",
    responses={404: {"model": ErrorResponse}},
)
async def get_document_chunks(
    document_id: str,
    container: ContainerDep,
    caller: RequireRead,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ChunkListResponse:
    record = container.document_service.get(document_id)
    chunks = container.document_service.chunks_for(document_id, limit=limit, offset=offset)
    return ChunkListResponse(
        chunks=[_chunk_to_response(c) for c in chunks],
        page=Page(limit=limit, offset=offset, total=record.chunk_count, returned=len(chunks)),
    )


@router.get(
    "/{document_id}/download",
    summary="Download the original uploaded file",
    responses={404: {"model": ErrorResponse}},
)
async def download_document(document_id: str, container: ContainerDep, caller: RequireRead) -> Response:
    data, filename, mime_type = container.document_service.original_bytes(document_id)
    # The filename is quoted and ASCII-sanitised; it is never used to build a path.
    safe = filename.encode("ascii", "ignore").decode("ascii").replace('"', "")
    return Response(
        content=data,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Activate/deactivate a document or correct its metadata",
    description=(
        "Deactivating excludes a document from retrieval while keeping it inspectable — the "
        "honest way to supersede a policy without destroying the audit trail that references "
        "it. Metadata corrections apply to the registry; re-index to refresh chunk copies."
    ),
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def patch_document(
    document_id: str,
    body: DocumentPatchRequest,
    container: ContainerDep,
    caller: RequireWrite,
) -> DocumentResponse:
    service = container.document_service
    metadata = body.model_dump(exclude_none=True, exclude={"status"})
    if metadata:
        service.update_metadata(document_id, **metadata)
    if body.status:
        service.set_status(document_id, body.status)
    return _to_response(service.get(document_id))


@router.post(
    "/{document_id}/reindex",
    response_model=UploadedDocument,
    summary="Re-run the ingestion pipeline for a document",
    description=(
        "Needed after a chunking or embedding change. Idempotent: the same document produces "
        "the same chunk identities."
    ),
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def reindex_document(
    document_id: str, container: ContainerDep, caller: RequireWrite
) -> UploadedDocument:
    result = await run_in_threadpool(container.document_service.reindex, document_id)
    return UploadedDocument(
        document=_to_response(result.document),
        chunks=result.chunks,
        duplicate_of=None,
        elapsed_ms=result.elapsed_ms,
    )


@router.delete(
    "/{document_id}",
    status_code=204,
    summary="Delete a document and remove its chunks from both indices",
    responses={404: {"model": ErrorResponse}},
)
async def delete_document(
    document_id: str,
    container: ContainerDep,
    caller: RequireWrite,
    purge_original: bool = Query(False, description="Also delete the stored original file."),
) -> Response:
    await run_in_threadpool(container.document_service.delete, document_id, purge_original=purge_original)
    return Response(status_code=204)
