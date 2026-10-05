"""Append-only JSON-Lines audit writer.

One AuditEntry per line. Captures everything a compliance officer needs to reconstruct
*exactly* what the AI was given and what it said for any past query — including the full
retrieved context, not just the citations that survived into the user-facing response.
"""

from __future__ import annotations

from pathlib import Path

from src.schemas import AuditEntry


def write_audit_entry(path: Path, entry: AuditEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")
