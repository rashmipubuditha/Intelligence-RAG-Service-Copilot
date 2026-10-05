"""Ingest orchestrator.

Wires the three ingest-side components together:
  policies/ → chunker → embedder → FAISS persistence under settings.vector_store_dir

Exposed as a single pure function so it can be called by main.py and reused by tests.
"""

from __future__ import annotations

from pathlib import Path

from src.chunker import chunk_corpus
from src.config import Settings
from src.embedder import Embedder
from src.vector_store import VectorStore


def run_ingest(policies_dir: Path, settings: Settings) -> dict:
    chunks = chunk_corpus(policies_dir)
    if not chunks:
        raise RuntimeError(f"No chunks produced from {policies_dir}")

    embedder = Embedder(settings.embedding_model)
    texts = [c.text for c in chunks]
    embeddings = embedder.encode(texts, normalize=True)

    store = VectorStore(dim=embedder.dim)
    store.add(embeddings, chunks)
    store.persist(settings.vector_store_dir)

    documents = sorted({c.document for c in chunks})
    return {
        "documents": len(documents),
        "document_names": documents,
        "chunks": len(chunks),
        "embedding_model": settings.embedding_model,
        "embedding_dim": embedder.dim,
        "vector_store_dir": str(settings.vector_store_dir),
    }
