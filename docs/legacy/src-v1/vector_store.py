"""Persistent FAISS vector store.

Three files on disk under `vector_store_dir`:
  - faiss.index   the FAISS IndexFlatIP (inner-product over L2-normalized vectors = cosine)
  - chunks.jsonl  one Chunk per line, in the same order as the FAISS rows
  - meta.json     dim and count, used to validate on load

IndexFlatIP was picked over IVF/HNSW: with ~50 chunks the brute-force cost is negligible,
and Flat is exact (no approximate-search recall loss to debug).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.schemas import Chunk

INDEX_FILE = "faiss.index"
CHUNKS_FILE = "chunks.jsonl"
META_FILE = "meta.json"


class VectorStore:
    def __init__(self, dim: int):
        import faiss

        self._faiss = faiss
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)
        self.chunks: list[Chunk] = []

    def add(self, embeddings: np.ndarray, chunks: list[Chunk]) -> None:
        if embeddings.shape[0] != len(chunks):
            raise ValueError(
                f"embeddings count ({embeddings.shape[0]}) does not match chunks count ({len(chunks)})"
            )
        if embeddings.shape[1] != self.dim:
            raise ValueError(
                f"embedding dim ({embeddings.shape[1]}) does not match index dim ({self.dim})"
            )
        self.index.add(embeddings)
        self.chunks.extend(chunks)

    def search(self, query_embedding: np.ndarray, k: int) -> list[tuple[Chunk, float]]:
        if self.index.ntotal == 0:
            return []
        k = min(k, self.index.ntotal)
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        scores, idx = self.index.search(query_embedding, k)
        results: list[tuple[Chunk, float]] = []
        for score, row in zip(scores[0], idx[0]):
            if row < 0:
                continue
            results.append((self.chunks[int(row)], float(score)))
        return results

    def persist(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self.index, str(directory / INDEX_FILE))
        with (directory / CHUNKS_FILE).open("w", encoding="utf-8") as f:
            for chunk in self.chunks:
                f.write(chunk.model_dump_json() + "\n")
        meta = {"dim": self.dim, "count": len(self.chunks)}
        (directory / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        meta_path = directory / META_FILE
        index_path = directory / INDEX_FILE
        chunks_path = directory / CHUNKS_FILE
        if not (meta_path.exists() and index_path.exists() and chunks_path.exists()):
            raise FileNotFoundError(
                f"Vector store not found at {directory}. Run `ingest` first."
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        store = cls(dim=int(meta["dim"]))
        store.index = store._faiss.read_index(str(index_path))
        with chunks_path.open("r", encoding="utf-8") as f:
            store.chunks = [Chunk.model_validate_json(line) for line in f if line.strip()]
        if store.index.ntotal != len(store.chunks):
            raise ValueError(
                f"Index/chunks size mismatch: index has {store.index.ntotal}, chunks file has {len(store.chunks)}"
            )
        return store
