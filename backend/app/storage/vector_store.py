"""Persistent FAISS vector store with stable ids and per-document deletion.

Changes from v1 (README D4/D5):
  - `IndexIDMap2` wraps `IndexFlatIP`, so every vector carries a stable int64 id assigned by
    the registry rather than its row position. Re-indexing one document no longer renumbers
    the corpus, and `remove_ids` makes per-document deletion possible.
  - Chunk payloads live in SQLite, not in a parallel JSONL whose ordering must be trusted.
    The index stores vectors only; `faiss_id` is the join key.
  - `meta.json` records the embedding model and dimension, and loading refuses an index
    built with a different model instead of silently returning nonsense.

Filtered search is exact by construction: when a filter is active we search the whole index
and intersect with the allowed id set. At this corpus size (tens to thousands of chunks)
brute force costs microseconds, and exactness beats a clever approximation that needs its
own debugging.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

INDEX_FILE = "faiss.index"
META_FILE = "meta.json"


class VectorStore:
    def __init__(self, dim: int, embedding_model: str = "") -> None:
        import faiss

        self._faiss = faiss
        self.dim = dim
        self.embedding_model = embedding_model
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    # --- mutation ----------------------------------------------------------
    def add(self, embeddings: np.ndarray, faiss_ids: list[int]) -> None:
        if embeddings.shape[0] != len(faiss_ids):
            raise ValueError(f"embedding count ({embeddings.shape[0]}) != id count ({len(faiss_ids)})")
        if embeddings.shape[0] == 0:
            return
        if embeddings.shape[1] != self.dim:
            raise ValueError(f"embedding dim ({embeddings.shape[1]}) != index dim ({self.dim})")
        ids = np.asarray(faiss_ids, dtype="int64")
        self.index.add_with_ids(np.ascontiguousarray(embeddings, dtype="float32"), ids)

    def remove(self, faiss_ids: list[int]) -> int:
        if not faiss_ids:
            return 0
        selector = self._faiss.IDSelectorArray(np.asarray(faiss_ids, dtype="int64"))
        return int(self.index.remove_ids(selector))

    def reset(self) -> None:
        self.index = self._faiss.IndexIDMap2(self._faiss.IndexFlatIP(self.dim))

    # --- search ------------------------------------------------------------
    def search(
        self,
        query_embedding: np.ndarray,
        k: int,
        allowed_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Return [(faiss_id, cosine_score)] best-first.

        Vectors are L2-normalised at encode time, so inner product == cosine similarity.
        """
        if self.ntotal == 0 or k <= 0:
            return []
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        query_embedding = np.ascontiguousarray(query_embedding, dtype="float32")

        # With a filter active, scan everything and intersect — exact and cheap at this size.
        search_k = self.ntotal if allowed_ids is not None else min(k, self.ntotal)
        scores, ids = self.index.search(query_embedding, search_k)

        out: list[tuple[int, float]] = []
        for score, fid in zip(scores[0], ids[0], strict=False):
            fid_int = int(fid)
            if fid_int < 0:
                continue
            if allowed_ids is not None and fid_int not in allowed_ids:
                continue
            out.append((fid_int, float(score)))
            if len(out) >= k:
                break
        return out

    # --- persistence -------------------------------------------------------
    @property
    def ntotal(self) -> int:
        return int(self.index.ntotal)

    def persist(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self.index, str(directory / INDEX_FILE))
        meta = {
            "dim": self.dim,
            "count": self.ntotal,
            "embedding_model": self.embedding_model,
            "index_type": "IndexIDMap2(IndexFlatIP)",
        }
        (directory / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load_or_create(cls, directory: Path, dim: int, embedding_model: str) -> VectorStore:
        """Load an existing index, or create an empty one.

        Refuses to load an index whose embedding model or dimension differs from the current
        configuration: mixing embedding spaces produces silently meaningless similarity
        scores, which is far worse than a loud failure.
        """
        index_path = directory / INDEX_FILE
        meta_path = directory / META_FILE
        store = cls(dim=dim, embedding_model=embedding_model)
        if not (index_path.exists() and meta_path.exists()):
            return store

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stored_model = meta.get("embedding_model") or ""
        stored_dim = int(meta.get("dim", dim))
        if stored_dim != dim or (stored_model and stored_model != embedding_model):
            raise ValueError(
                f"Index at {directory} was built with model={stored_model!r} dim={stored_dim} "
                f"but the configuration is model={embedding_model!r} dim={dim}. "
                "Re-run ingest (or rebuild-index) to rebuild the index."
            )
        store.index = store._faiss.read_index(str(index_path))
        return store
