"""Persisted BM25 sparse index.

v1 re-tokenised the entire corpus inside `HybridRetriever.__init__`, i.e. on every single
query (README D7). Here the tokenised corpus is persisted and the BM25 model is built once
per process, then rebuilt only when the corpus actually changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CORPUS_FILE = "bm25_corpus.jsonl"

_TOKEN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class BM25Store:
    def __init__(self) -> None:
        self._faiss_ids: list[int] = []
        self._tokens: list[list[str]] = []
        self._bm25: Any = None
        self._dirty = True

    # --- mutation ----------------------------------------------------------
    def add(self, faiss_id: int, text: str) -> None:
        self._faiss_ids.append(faiss_id)
        self._tokens.append(tokenize(text))
        self._dirty = True

    def add_many(self, items: list[tuple[int, str]]) -> None:
        for faiss_id, text in items:
            self.add(faiss_id, text)

    def remove(self, faiss_ids: set[int]) -> int:
        keep_ids: list[int] = []
        keep_tokens: list[list[str]] = []
        removed = 0
        for fid, toks in zip(self._faiss_ids, self._tokens, strict=True):
            if fid in faiss_ids:
                removed += 1
                continue
            keep_ids.append(fid)
            keep_tokens.append(toks)
        self._faiss_ids, self._tokens = keep_ids, keep_tokens
        self._dirty = True
        return removed

    def reset(self) -> None:
        self._faiss_ids, self._tokens, self._bm25 = [], [], None
        self._dirty = True

    # --- search ------------------------------------------------------------
    def _ensure_built(self) -> None:
        if not self._dirty and self._bm25 is not None:
            return
        if not self._tokens:
            self._bm25 = None
        else:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(self._tokens)
        self._dirty = False

    def search(self, query: str, k: int, allowed_ids: set[int] | None = None) -> list[tuple[int, float]]:
        self._ensure_built()
        if self._bm25 is None or k <= 0:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(
            (
                (self._faiss_ids[i], float(s))
                for i, s in enumerate(scores)
                if s > 0 and (allowed_ids is None or self._faiss_ids[i] in allowed_ids)
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[:k]

    # --- persistence -------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self._faiss_ids)

    def persist(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / CORPUS_FILE).open("w", encoding="utf-8") as f:
            for fid, toks in zip(self._faiss_ids, self._tokens, strict=True):
                f.write(json.dumps({"faiss_id": fid, "tokens": toks}) + "\n")

    @classmethod
    def load_or_create(cls, directory: Path) -> BM25Store:
        store = cls()
        path = directory / CORPUS_FILE
        if not path.exists():
            return store
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                store._faiss_ids.append(int(row["faiss_id"]))
                store._tokens.append(list(row["tokens"]))
        store._dirty = True
        return store
