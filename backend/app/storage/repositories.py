"""Repositories — the only place that knows SQL.

Services talk to repositories in domain objects; nothing above this layer sees a sqlite3.Row.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from typing import Any

from app.models import (
    Chunk,
    ChunkMetadata,
    DocumentRecord,
    DocumentStatus,
    RetrievalFilters,
    utc_now_iso,
)
from app.storage.db import Database, dumps, loads


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row_to_record(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            filename=row["filename"],
            title=row["title"],
            doc_type=row["doc_type"],
            version=row["version"],
            effective_date=_as_date(row["effective_date"]),
            publication_date=_as_date(row["publication_date"]),
            owner=row["owner"],
            review_cycle=row["review_cycle"],
            status=row["status"],
            content_sha256=row["content_sha256"],
            byte_size=row["byte_size"],
            mime_type=row["mime_type"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            embedding_model=row["embedding_model"],
            uploaded_at=row["uploaded_at"],
            indexed_at=row["indexed_at"],
            failure_reason=row["failure_reason"],
            injection_flags=loads(row["injection_flags"], []),
            family_key=row["family_key"],
            tenant_id=row["tenant_id"],
        )

    def create(self, record: DocumentRecord) -> DocumentRecord:
        with self.db.write() as cur:
            cur.execute(
                """
                INSERT INTO documents (id, filename, title, doc_type, version, effective_date,
                    publication_date, owner, review_cycle, status, content_sha256, byte_size,
                    mime_type, page_count, chunk_count, embedding_model, uploaded_at,
                    indexed_at, failure_reason, injection_flags, family_key, tenant_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.filename,
                    record.title,
                    record.doc_type,
                    record.version,
                    record.effective_date.isoformat() if record.effective_date else None,
                    record.publication_date.isoformat() if record.publication_date else None,
                    record.owner,
                    record.review_cycle,
                    record.status,
                    record.content_sha256,
                    record.byte_size,
                    record.mime_type,
                    record.page_count,
                    record.chunk_count,
                    record.embedding_model,
                    record.uploaded_at,
                    record.indexed_at,
                    record.failure_reason,
                    dumps(record.injection_flags),
                    record.family_key,
                    record.tenant_id,
                ),
            )
        return record

    def get(self, document_id: str) -> DocumentRecord | None:
        row = self.db.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        return self._row_to_record(row) if row else None

    def get_by_hash(self, content_sha256: str) -> DocumentRecord | None:
        row = self.db.query_one("SELECT * FROM documents WHERE content_sha256 = ?", (content_sha256,))
        return self._row_to_record(row) if row else None

    def list(
        self,
        *,
        status: str | None = None,
        doc_type: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        if search:
            sql += " AND (LOWER(title) LIKE ? OR LOWER(filename) LIKE ?)"
            needle = f"%{search.lower()}%"
            params += [needle, needle]
        sql += " ORDER BY uploaded_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [self._row_to_record(r) for r in self.db.query(sql, params)]

    def count(self, *, status: str | None = None) -> int:
        if status:
            row = self.db.query_one("SELECT COUNT(*) AS n FROM documents WHERE status = ?", (status,))
        else:
            row = self.db.query_one("SELECT COUNT(*) AS n FROM documents")
        return int(row["n"]) if row else 0

    def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        failure_reason: str | None = None,
        indexed: bool = False,
        embedding_model: str | None = None,
        injection_flags: list[str] | None = None,
        page_count: int | None = None,
    ) -> None:
        sets = ["status = ?"]
        params: list[Any] = [status]
        if chunk_count is not None:
            sets.append("chunk_count = ?")
            params.append(chunk_count)
        if failure_reason is not None or status != "failed":
            sets.append("failure_reason = ?")
            params.append(failure_reason)
        if indexed:
            sets.append("indexed_at = ?")
            params.append(utc_now_iso())
        if embedding_model is not None:
            sets.append("embedding_model = ?")
            params.append(embedding_model)
        if injection_flags is not None:
            sets.append("injection_flags = ?")
            params.append(dumps(injection_flags))
        if page_count is not None:
            sets.append("page_count = ?")
            params.append(page_count)
        params.append(document_id)
        with self.db.write() as cur:
            cur.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", params)

    def update_metadata(self, document_id: str, **fields: Any) -> None:
        allowed = {
            "title",
            "doc_type",
            "version",
            "effective_date",
            "publication_date",
            "owner",
            "review_cycle",
            "family_key",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        sets = ", ".join(f"{k} = ?" for k in updates)
        params = [v.isoformat() if isinstance(v, date) else v for v in updates.values()]
        params.append(document_id)
        with self.db.write() as cur:
            cur.execute(f"UPDATE documents SET {sets} WHERE id = ?", params)

    def delete(self, document_id: str) -> None:
        with self.db.write() as cur:
            cur.execute("DELETE FROM documents WHERE id = ?", (document_id,))


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class ChunkRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_uid=row["chunk_uid"],
            faiss_id=row["faiss_id"],
            text=row["text"],
            metadata=ChunkMetadata.model_validate(loads(row["metadata"], {})),
        )

    def next_faiss_id(self) -> int:
        row = self.db.query_one("SELECT COALESCE(MAX(faiss_id), 0) + 1 AS next FROM chunks")
        return int(row["next"]) if row else 1

    def add_many(self, chunks: list[Chunk]) -> None:
        with self.db.write() as cur:
            cur.executemany(
                """
                INSERT OR REPLACE INTO chunks (chunk_uid, faiss_id, document_id, chunk_index,
                    text, metadata, char_count, token_estimate, content_sha256)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        c.chunk_uid,
                        c.faiss_id,
                        c.metadata.document_id,
                        c.metadata.chunk_index,
                        c.text,
                        dumps(c.metadata.model_dump(mode="json")),
                        c.metadata.char_count,
                        c.metadata.token_estimate,
                        c.metadata.content_sha256,
                    )
                    for c in chunks
                ],
            )

    def get_by_faiss_ids(self, faiss_ids: list[int]) -> dict[int, Chunk]:
        if not faiss_ids:
            return {}
        placeholders = ",".join("?" * len(faiss_ids))
        rows = self.db.query(f"SELECT * FROM chunks WHERE faiss_id IN ({placeholders})", list(faiss_ids))
        return {int(r["faiss_id"]): self._row_to_chunk(r) for r in rows}

    def get_by_uid(self, chunk_uid: str) -> Chunk | None:
        row = self.db.query_one("SELECT * FROM chunks WHERE chunk_uid = ?", (chunk_uid,))
        return self._row_to_chunk(row) if row else None

    def list_for_document(self, document_id: str, limit: int = 500, offset: int = 0) -> list[Chunk]:
        rows = self.db.query(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ? OFFSET ?",
            (document_id, limit, offset),
        )
        return [self._row_to_chunk(r) for r in rows]

    def faiss_ids_for_document(self, document_id: str) -> list[int]:
        rows = self.db.query("SELECT faiss_id FROM chunks WHERE document_id = ?", (document_id,))
        return [int(r["faiss_id"]) for r in rows]

    def all_faiss_ids(self) -> list[int]:
        return [int(r["faiss_id"]) for r in self.db.query("SELECT faiss_id FROM chunks")]

    def all_chunks(self) -> list[Chunk]:
        rows = self.db.query("SELECT * FROM chunks ORDER BY faiss_id")
        return [self._row_to_chunk(r) for r in rows]

    def delete_for_document(self, document_id: str) -> list[int]:
        ids = self.faiss_ids_for_document(document_id)
        with self.db.write() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        return ids

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM chunks")
        return int(row["n"]) if row else 0

    def allowed_faiss_ids(self, filters: RetrievalFilters) -> set[int] | None:
        """Resolve retrieval filters to the set of searchable faiss ids.

        Returns None when no filtering is needed (everything indexed is searchable), which
        lets the vector store take its fast path.
        """
        sql = "SELECT c.faiss_id FROM chunks c JOIN documents d ON d.id = c.document_id WHERE 1=1"
        params: list[Any] = []
        unfiltered = True

        if not filters.include_inactive:
            sql += " AND d.status = 'indexed'"
        if filters.document_ids:
            placeholders = ",".join("?" * len(filters.document_ids))
            sql += f" AND d.id IN ({placeholders})"
            params += list(filters.document_ids)
            unfiltered = False
        if filters.doc_types:
            placeholders = ",".join("?" * len(filters.doc_types))
            sql += f" AND d.doc_type IN ({placeholders})"
            params += list(filters.doc_types)
            unfiltered = False
        if filters.effective_from:
            sql += " AND (d.effective_date IS NULL OR d.effective_date >= ?)"
            params.append(filters.effective_from.isoformat())
            unfiltered = False
        if filters.effective_to:
            sql += " AND (d.effective_date IS NULL OR d.effective_date <= ?)"
            params.append(filters.effective_to.isoformat())
            unfiltered = False
        if filters.tenant_id:
            sql += " AND d.tenant_id = ?"
            params.append(filters.tenant_id)

        rows = self.db.query(sql, params)
        allowed = {int(r["faiss_id"]) for r in rows}

        # Fast path only when nothing could have been excluded.
        if unfiltered and not filters.include_inactive:
            total = self.count()
            if len(allowed) == total:
                return None
        return allowed


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, title: str = "New conversation", tenant_id: str = "default") -> str:
        cid = new_id("conv")
        now = utc_now_iso()
        with self.db.write() as cur:
            cur.execute(
                """INSERT INTO conversations (id, title, created_at, updated_at, message_count,
                   tenant_id) VALUES (?,?,?,?,0,?)""",
                (cid, title[:120], now, now, tenant_id),
            )
        return cid

    def exists(self, conversation_id: str) -> bool:
        return self.db.query_one("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)) is not None

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        return dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM conversations")
        return int(row["n"]) if row else 0

    def delete(self, conversation_id: str) -> None:
        with self.db.write() as cur:
            cur.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        **extra: Any,
    ) -> str:
        mid = new_id("msg")
        now = utc_now_iso()
        with self.db.write() as cur:
            cur.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, created_at, model,
                    evidence, conflicts, citations, retrieval_params, timings, token_usage,
                    refused, request_id, error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mid,
                    conversation_id,
                    role,
                    content,
                    now,
                    extra.get("model"),
                    dumps(extra["evidence"]) if extra.get("evidence") is not None else None,
                    dumps(extra["conflicts"]) if extra.get("conflicts") is not None else None,
                    dumps(extra["citations"]) if extra.get("citations") is not None else None,
                    dumps(extra["retrieval_params"]) if extra.get("retrieval_params") is not None else None,
                    dumps(extra["timings"]) if extra.get("timings") is not None else None,
                    dumps(extra["token_usage"]) if extra.get("token_usage") is not None else None,
                    1 if extra.get("refused") else 0,
                    extra.get("request_id"),
                    extra.get("error"),
                ),
            )
            cur.execute(
                """UPDATE conversations
                   SET updated_at = ?, message_count = message_count + 1,
                       title = CASE WHEN message_count = 0 AND ? = 'user'
                                    THEN substr(?, 1, 80) ELSE title END
                   WHERE id = ?""",
                (now, role, content, conversation_id),
            )
        return mid

    def messages(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at LIMIT ?",
            (conversation_id, limit),
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for field in ("evidence", "conflicts", "citations", "retrieval_params", "timings", "token_usage"):
                d[field] = loads(d.get(field), None)
            d["refused"] = bool(d.get("refused"))
            out.append(d)
        return out

    def recent_turns(self, conversation_id: str, turns: int = 4) -> list[tuple[str, str]]:
        """Last N (role, content) pairs, oldest first — input to query rewriting."""
        rows = self.db.query(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, turns),
        )
        return [(r["role"], r["content"]) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Evaluation + query log
# ---------------------------------------------------------------------------


class EvalRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_run(self, dataset: str, mode: str, config: dict[str, Any], n_questions: int) -> str:
        rid = new_id("run")
        with self.db.write() as cur:
            cur.execute(
                """INSERT INTO eval_runs (id, dataset, mode, status, started_at, config,
                   metrics, n_questions) VALUES (?,?,?,'running',?,?,'{}',?)""",
                (rid, dataset, mode, utc_now_iso(), dumps(config), n_questions),
            )
        return rid

    def finish_run(
        self, run_id: str, metrics: dict[str, Any], status: str = "completed", error: str | None = None
    ) -> None:
        with self.db.write() as cur:
            cur.execute(
                "UPDATE eval_runs SET status=?, finished_at=?, metrics=?, error=? WHERE id=?",
                (status, utc_now_iso(), dumps(metrics), error, run_id),
            )

    def add_result(self, run_id: str, question_id: str, payload: dict[str, Any]) -> None:
        with self.db.write() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO eval_results (run_id, question_id, payload) VALUES (?,?,?)",
                (run_id, question_id, dumps(payload)),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM eval_runs WHERE id = ?", (run_id,))
        if not row:
            return None
        run = dict(row)
        run["config"] = loads(run["config"], {})
        run["metrics"] = loads(run["metrics"], {})
        run["results"] = [
            loads(r["payload"], {})
            for r in self.db.query(
                "SELECT payload FROM eval_results WHERE run_id = ? ORDER BY question_id", (run_id,)
            )
        ]
        return run

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            run = dict(r)
            run["config"] = loads(run["config"], {})
            run["metrics"] = loads(run["metrics"], {})
            out.append(run)
        return out


class QueryLogRepository:
    """Analytics only: hashes and counters, never question text (README §16)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, **fields: Any) -> None:
        with self.db.write() as cur:
            cur.execute(
                """
                INSERT INTO query_log (id, request_id, created_at, question_hash, question_len,
                    top_k, rerank_enabled, model, n_retrieved, n_cited, evidence_band, refused,
                    retrieval_ms, rerank_ms, llm_ms, total_ms, prompt_tokens, completion_tokens,
                    error_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("q"),
                    fields.get("request_id"),
                    utc_now_iso(),
                    fields.get("question_hash", ""),
                    fields.get("question_len", 0),
                    fields.get("top_k", 0),
                    1 if fields.get("rerank_enabled") else 0,
                    fields.get("model"),
                    fields.get("n_retrieved", 0),
                    fields.get("n_cited", 0),
                    fields.get("evidence_band"),
                    1 if fields.get("refused") else 0,
                    fields.get("retrieval_ms", 0),
                    fields.get("rerank_ms", 0),
                    fields.get("llm_ms", 0),
                    fields.get("total_ms", 0),
                    fields.get("prompt_tokens"),
                    fields.get("completion_tokens"),
                    fields.get("error_code"),
                ),
            )

    def stats(self) -> dict[str, Any]:
        row = self.db.query_one(
            """
            SELECT COUNT(*) AS total,
                   SUM(refused) AS refused,
                   AVG(total_ms) AS avg_ms,
                   AVG(retrieval_ms) AS avg_retrieval_ms,
                   AVG(llm_ms) AS avg_llm_ms,
                   SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM query_log
            """
        )
        total = int(row["total"] or 0) if row else 0
        latencies = [r["total_ms"] for r in self.db.query("SELECT total_ms FROM query_log ORDER BY total_ms")]

        def pct(p: float) -> int:
            if not latencies:
                return 0
            idx = min(len(latencies) - 1, round(p * (len(latencies) - 1)))
            return latencies[idx]

        return {
            "queries_total": total,
            "refusals": int(row["refused"] or 0) if row else 0,
            "errors": int(row["errors"] or 0) if row else 0,
            "avg_total_ms": int(row["avg_ms"] or 0) if row else 0,
            "avg_retrieval_ms": int(row["avg_retrieval_ms"] or 0) if row else 0,
            "avg_llm_ms": int(row["avg_llm_ms"] or 0) if row else 0,
            "p50_total_ms": pct(0.50),
            "p95_total_ms": pct(0.95),
        }

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT created_at, question_hash, question_len, model, n_cited, evidence_band,
               refused, total_ms, error_code FROM query_log ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]
