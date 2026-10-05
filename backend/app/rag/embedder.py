"""Embedding provider.

Two changes from v1:

  1. **Asymmetric encoding (fixes README D3).** BGE v1.5 is trained with an instruction
     prefix on queries and bare passages. v1 encoded the raw question, leaving measurable
     retrieval quality on the table for the cost of one line. `encode_queries` applies the
     prefix; `encode_passages` deliberately does not.
  2. **Process-lifetime singleton.** v1 loaded the model per CLI invocation (~2–3 s of the
     ~22 s end-to-end latency). Cached by model name, the server pays it once at startup.

The interface is narrow on purpose so an API-based provider can be dropped in without
touching retrieval code.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

_CACHE: dict[str, Embedder] = {}


class EmbeddingProvider(Protocol):
    model_name: str

    @property
    def dim(self) -> int: ...

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class Embedder:
    """Local sentence-transformers embedder. Vectors are L2-normalised so that an inner
    product search over FAISS is exactly cosine similarity."""

    def __init__(
        self,
        model_name: str,
        *,
        query_prefix: str = "",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.query_prefix = query_prefix.strip()
        self.batch_size = batch_size
        self._model = None  # lazy: importing this module must not load a model
        self._dim: int | None = None

    # --- model -------------------------------------------------------------
    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def warm_up(self) -> None:
        """Called at server startup so the first user request is not the one that waits."""
        self.encode_queries(["warm up"])

    @property
    def dim(self) -> int:
        if self._dim is None:
            model = self._load()
            getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
            self._dim = int(getter())
        return self._dim

    # --- encoding ----------------------------------------------------------
    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        items = list(texts)
        if not items:
            return np.zeros((0, self.dim), dtype="float32")
        model = self._load()
        vectors = model.encode(
            items,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype="float32")

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Passages are embedded bare — this is what the BGE recipe specifies."""
        return self._encode(texts)

    def encode_queries(self, texts: Iterable[str]) -> np.ndarray:
        """Queries get the retrieval instruction prefix."""
        items = list(texts)
        if self.query_prefix:
            items = [f"{self.query_prefix} {t}" for t in items]
        return self._encode(items)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_queries([text])


def get_embedder(model_name: str, *, query_prefix: str = "", batch_size: int = 32) -> Embedder:
    """Cached per model name so one process loads each model at most once."""
    key = f"{model_name}|{query_prefix}|{batch_size}"
    if key not in _CACHE:
        _CACHE[key] = Embedder(model_name, query_prefix=query_prefix, batch_size=batch_size)
    return _CACHE[key]


def clear_embedder_cache() -> None:
    _CACHE.clear()
