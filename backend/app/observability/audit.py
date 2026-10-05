"""Append-only JSON-Lines audit writer.

Unchanged in purpose from v1 and deliberately unchanged in format: one `AuditEntry` per
line, append-only, so a compliance officer can reconstruct exactly what the model was given
and what it said for any past query. New fields (request id, retrieval parameters, evidence,
token usage) are additive, so existing readers of audit.log keep working.

This file is the one place in the system that *does* record full question text and full
retrieved context. That is its regulatory purpose, it is local, and it is documented.
Application logs record a hash instead (see core/logging.py).

Rotation is by size: an audit log is never truncated or rewritten in place — it is closed and
a new file is started, with the old one kept.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.logging import get_logger
from app.models import AnswerResult, AuditEntry

log = get_logger("audit")

MAX_BYTES = 50 * 1024 * 1024  # 50 MB, then rotate


def write_audit_entry(path: Path, entry: AuditEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def build_audit_entry(result: AnswerResult, *, conversation_id: str | None = None) -> AuditEntry:
    return AuditEntry(
        question=result.question,
        response=result.to_legacy_response(),
        retrieved_context=[rc.chunk for rc in result.retrieved],
        model=result.model,
        latency_ms=result.timings.total_ms,
        timestamp=result.timestamp,
        error=result.error,
        request_id=result.request_id,
        conversation_id=conversation_id,
        rewritten_question=result.rewritten_question,
        retrieval_params=result.retrieval_params,
        evidence=result.evidence,
        token_usage=result.token_usage,
        timings=result.timings,
    )


def audit_answer(path: Path, result: AnswerResult, *, conversation_id: str | None = None) -> None:
    """Write one audit entry. An audit failure must never break the user's request, but it
    must be loud in the logs — a silently missing audit trail is the worst outcome here."""
    try:
        write_audit_entry(path, build_audit_entry(result, conversation_id=conversation_id))
    except Exception as exc:
        log.error("audit.write_failed", error=str(exc), path=str(path))


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path.rename(path.with_name(f"{path.stem}.{stamp}{path.suffix}"))
    except OSError as exc:
        log.warning("audit.rotation_failed", error=str(exc))


def read_recent_entries(path: Path, limit: int = 20) -> list[dict]:
    """Tail the audit log. Used by the API to show recent activity without a second store."""
    import json

    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out
