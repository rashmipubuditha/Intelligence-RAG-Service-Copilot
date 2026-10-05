"""CLI entry point.

The original two commands keep their exact contract — this matters, because the CLI is the
documented interface the project was first built against:

    ingest --docs <folder>              chunk + embed + index, prints a JSON summary
    query  --question <text> [--k N]    retrieve, answer, audit, prints one JSON object

Both still print a single JSON object to stdout and nothing else, and `query` still appends
one JSON-Lines entry to audit.log on every call, success or failure.

Added commands (additive, no change to the above):

    serve                               run the FastAPI application
    evaluate [--mode ...]               run the evaluation harness
    reindex --id <document_id>          re-run ingestion for one document
    rebuild-index                       rebuild FAISS + BM25 from the registry
    documents                           list indexed documents

Fixed from v1 (README D12): an unhandled exception now still writes an audit entry and exits
non-zero, instead of printing JSON and exiting 0 with no audit trail.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Silence HuggingFace chatter before any import that triggers it, so stdout stays clean.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_PATH = PROJECT_ROOT / "backend"

# Policy text contains non-ASCII punctuation (non-breaking hyphens, en dashes, curly quotes).
# Windows consoles default to cp1252, which cannot encode them, so a perfectly good answer
# would die at the print. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import typer  # noqa: E402

app = typer.Typer(
    add_completion=False,
    help="Compliance Intelligence Copilot — RAG over AML/KYC compliance documents.",
    no_args_is_help=True,
)


def _print_json(payload: dict | list) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _build_container():
    from app.container import AppContainer
    from app.core.config import get_settings
    from app.core.logging import configure_logging

    settings = get_settings()
    # Logs go to stderr so stdout remains a single JSON object, as the contract requires.
    configure_logging(settings.log_level, settings.log_format)
    return AppContainer(settings)


# ---------------------------------------------------------------------------


@app.command()
def ingest(
    docs: Path = typer.Option(..., "--docs", help="Folder containing documents to index."),
    replace: bool = typer.Option(
        False, "--replace", help="Re-index documents whose content is already indexed."
    ),
) -> None:
    """Chunk, embed, and index every supported document in a folder."""
    container = _build_container()
    try:
        summary = container.document_service.ingest_directory(docs, replace=replace)
        _print_json({"status": "ok", **summary})
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1) from exc
    finally:
        container.shutdown()


@app.command()
def query(
    question: str = typer.Option(..., "--question", help="The compliance question to ask."),
    k: int = typer.Option(3, "--k", help="Number of passages to retrieve. Default: 3."),
    conversation: str = typer.Option(None, "--conversation", help="Continue an existing conversation by id."),
) -> None:
    """Answer a compliance question. Always prints one structured JSON object to stdout."""
    from app.models import QueryResponse, utc_now_iso

    container = None
    try:
        container = _build_container()
        _conversation_id, result = container.chat_service.ask(
            question, conversation_id=conversation, k=k, use_history=bool(conversation)
        )
        _print_json(result.to_legacy_response().model_dump(mode="json"))
        raise typer.Exit(code=1 if result.error else 0)
    except typer.Exit:
        raise
    except Exception as exc:
        # Last-resort safety net: stdout stays a valid response object, the failure is
        # audited, and the exit code signals failure (v1 silently exited 0 here).
        response = QueryResponse(
            question=question,
            answer="",
            citations=[],
            model="unknown",
            latency_ms=0,
            timestamp=utc_now_iso(),
            error=f"Unhandled error: {exc}",
        )
        if container is not None:
            try:
                from app.models import AuditEntry
                from app.observability.audit import write_audit_entry

                write_audit_entry(
                    container.settings.audit_log_path,
                    AuditEntry(
                        question=question,
                        response=response,
                        retrieved_context=[],
                        model="unknown",
                        latency_ms=0,
                        timestamp=response.timestamp,
                        error=response.error,
                    ),
                )
            except Exception:
                pass  # an audit failure must not mask the original error
        _print_json(response.model_dump(mode="json"))
        raise typer.Exit(code=1) from exc
    finally:
        if container is not None:
            container.shutdown()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev)."),
) -> None:
    """Run the FastAPI application."""
    import uvicorn

    typer.echo(f"API:  http://{host}:{port}/api/health", err=True)
    typer.echo(f"Docs: http://{host}:{port}/docs", err=True)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        app_dir=str(BACKEND_PATH),
        log_config=None,
    )


@app.command()
def evaluate(
    mode: str = typer.Option("retrieval_only", "--mode", help="retrieval_only | full"),
    dataset: str = typer.Option("aml_kyc_golden_v1", "--dataset"),
    top_k: int = typer.Option(None, "--top-k"),
    rerank: bool = typer.Option(None, "--rerank/--no-rerank"),
    judge: bool = typer.Option(False, "--judge", help="Add LLM-judged metrics (full mode)."),
    limit: int = typer.Option(None, "--limit"),
    categories: str = typer.Option(None, "--categories", help="Comma-separated filter."),
    min_recall_at_5: float = typer.Option(None, "--min-recall-at-5", help="CI gate threshold."),
) -> None:
    """Run the evaluation harness and print a markdown report."""
    from eval.run import main as eval_main

    argv = ["--mode", mode, "--dataset", dataset]
    if top_k is not None:
        argv += ["--top-k", str(top_k)]
    if rerank is not None:
        argv += ["--rerank", "true" if rerank else "false"]
    if judge:
        argv += ["--judge"]
    if limit is not None:
        argv += ["--limit", str(limit)]
    if categories:
        argv += ["--categories", categories]
    if min_recall_at_5 is not None:
        argv += ["--min-recall-at-5", str(min_recall_at_5)]
    raise typer.Exit(code=eval_main(argv))


@app.command()
def documents() -> None:
    """List indexed documents as JSON."""
    container = _build_container()
    try:
        records = container.document_service.list(limit=200)
        _print_json(
            {
                "count": len(records),
                "total_chunks": container.chunks.count(),
                "documents": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "filename": r.filename,
                        "type": r.doc_type,
                        "version": r.version,
                        "effective_date": r.effective_date,
                        "status": r.status,
                        "chunks": r.chunk_count,
                        "injection_flags": len(r.injection_flags),
                    }
                    for r in records
                ],
            }
        )
    finally:
        container.shutdown()


@app.command()
def reindex(
    document_id: str = typer.Option(..., "--id", help="Document id to re-index."),
) -> None:
    """Re-run the ingestion pipeline for one document."""
    container = _build_container()
    try:
        result = container.document_service.reindex(document_id)
        _print_json(
            {
                "status": "ok",
                "document_id": result.document.id,
                "title": result.document.title,
                "chunks": result.chunks,
                "elapsed_ms": result.elapsed_ms,
            }
        )
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1) from exc
    finally:
        container.shutdown()


@app.command(name="rebuild-index")
def rebuild_index() -> None:
    """Rebuild FAISS and BM25 from the chunk registry — the documented recovery path."""
    container = _build_container()
    try:
        _print_json({"status": "ok", **container.ingestion.rebuild_all()})
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1) from exc
    finally:
        container.shutdown()


if __name__ == "__main__":
    app()
