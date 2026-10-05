"""SQLite access layer.

Why SQLite and no ORM: see README DR-8. Eight tables of explicit SQL is less code than
configuring an ORM, keeps the schema readable, and adds no dependency.

Concurrency: one connection shared process-wide with `check_same_thread=False`, WAL mode
for concurrent readers, and a write lock held around mutating statements. That is correct
for a single-replica deployment and is exactly the constraint documented in the README.

Migrations are versioned SQL statements applied in order and tracked in `schema_version`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS documents (
            id              TEXT PRIMARY KEY,
            filename        TEXT NOT NULL,
            title           TEXT NOT NULL,
            doc_type        TEXT NOT NULL DEFAULT 'other',
            version         TEXT,
            effective_date  TEXT,
            publication_date TEXT,
            owner           TEXT,
            review_cycle    TEXT,
            status          TEXT NOT NULL DEFAULT 'processing',
            content_sha256  TEXT NOT NULL,
            byte_size       INTEGER NOT NULL DEFAULT 0,
            mime_type       TEXT NOT NULL DEFAULT '',
            page_count      INTEGER,
            chunk_count     INTEGER NOT NULL DEFAULT 0,
            embedding_model TEXT,
            uploaded_at     TEXT NOT NULL,
            indexed_at      TEXT,
            failure_reason  TEXT,
            injection_flags TEXT NOT NULL DEFAULT '[]',
            family_key      TEXT NOT NULL DEFAULT '',
            tenant_id       TEXT NOT NULL DEFAULT 'default'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_sha ON documents(content_sha256);
        CREATE INDEX IF NOT EXISTS ix_documents_status ON documents(status);
        CREATE INDEX IF NOT EXISTS ix_documents_family ON documents(family_key);

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_uid    TEXT PRIMARY KEY,
            faiss_id     INTEGER NOT NULL UNIQUE,
            document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index  INTEGER NOT NULL DEFAULT 0,
            text         TEXT NOT NULL,
            metadata     TEXT NOT NULL,
            char_count   INTEGER NOT NULL DEFAULT 0,
            token_estimate INTEGER NOT NULL DEFAULT 0,
            content_sha256 TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS ix_chunks_document ON chunks(document_id);

        CREATE TABLE IF NOT EXISTS conversations (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL DEFAULT 'New conversation',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            tenant_id     TEXT NOT NULL DEFAULT 'default'
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            model           TEXT,
            evidence        TEXT,
            conflicts       TEXT,
            citations       TEXT,
            retrieval_params TEXT,
            timings         TEXT,
            token_usage     TEXT,
            refused         INTEGER NOT NULL DEFAULT 0,
            request_id      TEXT,
            error           TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_messages_conversation
            ON messages(conversation_id, created_at);

        CREATE TABLE IF NOT EXISTS eval_runs (
            id          TEXT PRIMARY KEY,
            dataset     TEXT NOT NULL,
            mode        TEXT NOT NULL,
            status      TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            config      TEXT NOT NULL DEFAULT '{}',
            metrics     TEXT NOT NULL DEFAULT '{}',
            n_questions INTEGER NOT NULL DEFAULT 0,
            notes       TEXT,
            error       TEXT
        );

        CREATE TABLE IF NOT EXISTS eval_results (
            run_id      TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            question_id TEXT NOT NULL,
            payload     TEXT NOT NULL,
            PRIMARY KEY (run_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS query_log (
            id            TEXT PRIMARY KEY,
            request_id    TEXT,
            created_at    TEXT NOT NULL,
            question_hash TEXT NOT NULL,
            question_len  INTEGER NOT NULL,
            top_k         INTEGER NOT NULL DEFAULT 0,
            rerank_enabled INTEGER NOT NULL DEFAULT 0,
            model         TEXT,
            n_retrieved   INTEGER NOT NULL DEFAULT 0,
            n_cited       INTEGER NOT NULL DEFAULT 0,
            evidence_band TEXT,
            refused       INTEGER NOT NULL DEFAULT 0,
            retrieval_ms  INTEGER NOT NULL DEFAULT 0,
            rerank_ms     INTEGER NOT NULL DEFAULT 0,
            llm_ms        INTEGER NOT NULL DEFAULT 0,
            total_ms      INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            error_code    TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_query_log_created ON query_log(created_at);
        """,
    ),
]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    # --- schema ------------------------------------------------------------
    def migrate(self) -> None:
        with self.write() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
            row = cur.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, script in MIGRATIONS:
                if version > current:
                    cur.executescript(script)
                    cur.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    # --- access ------------------------------------------------------------
    @contextmanager
    def write(self) -> Iterator[sqlite3.Cursor]:
        """Transactional write. Commits on success, rolls back on any exception."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def query(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
