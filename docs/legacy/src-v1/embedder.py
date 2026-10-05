"""SentenceTransformer wrapper.

Lazy-loaded: importing this module does NOT load the model. The model is constructed on
first use of `encode`, so unit tests for chunking / config don't pay the load cost.

BGE models are trained with cosine similarity; we normalize embeddings here so the FAISS
IndexFlatIP (inner product) is equivalent to cosine similarity.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np


class Embedder:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None  # lazy

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        model = self._load()
        # sentence-transformers renamed get_sentence_embedding_dimension → get_embedding_dimension
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

    def encode(self, texts: Iterable[str], *, normalize: bool = True) -> np.ndarray:
        items = list(texts)
        if not items:
            return np.zeros((0, self.dim), dtype="float32")
        model = self._load()
        embeddings = model.encode(
            items,
            normalize_embeddings=normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embeddings.astype("float32")
