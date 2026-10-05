"""Shared fixtures.

The whole fast suite runs with **no network, no API key, and no model downloads**. That is
what the fakes below buy: a deterministic hash-based embedder instead of BGE-small, and a
scripted LLM instead of Groq. Tests that genuinely need the real models are marked `slow`.

The fake embedder is not a stub that returns zeros — it produces stable vectors with real
lexical overlap signal, so retrieval tests actually exercise ranking rather than trivially
returning insertion order.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
import pytest
from app.container import AppContainer
from app.core.config import Settings
from app.models import TokenUsage

TOKEN = re.compile(r"\w+")


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder.

    Vectors are L2-normalised, so cosine similarity behaves and lexically similar texts score
    higher — enough signal for retrieval ranking tests, with zero load time.
    """

    def __init__(self, dim: int = 64) -> None:
        self.model_name = "fake-embedder"
        self._dim = dim
        self.query_prefix = "query:"
        self.calls: list[str] = []

    @property
    def dim(self) -> int:
        return self._dim

    def warm_up(self) -> None:
        return None

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype="float32")
        for token in TOKEN.findall(text.lower()):
            index = int(hashlib.md5(token.encode()).hexdigest(), 16) % self._dim
            vec[index] += 1.0
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype="float32")
        return np.vstack([self._vector(t) for t in texts]).astype("float32")

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(list(texts))

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        items = list(texts)
        self.calls.extend(items)
        return self._encode(items)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_queries([text])


class FakeLLM:
    """Scripted provider.

    `json_responses` / `stream_responses` are consumed in order; `failures` lets a test force
    the repair path or a transport error.
    """

    provider_name = "fake"

    def __init__(
        self,
        *,
        json_responses: list[dict] | None = None,
        stream_responses: list[str] | None = None,
        fail_times: int = 0,
    ) -> None:
        self.model_name = "fake-model"
        self.json_responses = list(json_responses or [])
        self.stream_responses = list(stream_responses or [])
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []

    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int, temperature: float = 0.0
    ) -> dict:
        self.calls.append((system_prompt, user_prompt))
        if self.fail_times > 0:
            self.fail_times -= 1
            from app.core.errors import LLMError

            raise LLMError("scripted failure")
        if not self.json_responses:
            return {"answer": "fake answer", "used_chunk_ids": []}
        return self.json_responses.pop(0)

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout: int,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> Iterator[str]:
        self.calls.append((system_prompt, user_prompt))
        if self.fail_times > 0:
            self.fail_times -= 1
            from app.core.errors import LLMError

            raise LLMError("scripted stream failure")
        text = self.stream_responses.pop(0) if self.stream_responses else "fake streamed answer"
        # Emit in small pieces so marker-splitting across token boundaries is exercised.
        for index in range(0, len(text), 7):
            yield text[index : index + 7]

    def health(self) -> tuple[bool, str]:
        return True, "fake provider"

    def last_usage(self) -> TokenUsage:
        return TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)


class FakeReranker:
    """Reverses the candidate order so a test can prove reranking actually took effect."""

    enabled = True
    model_name = "fake-reranker"

    def rerank(self, query: str, candidates: list) -> list:
        reversed_candidates = list(reversed(candidates))
        return [
            rc.model_copy(
                update={"rerank_score": float(len(candidates) - i), "score": float(len(candidates) - i)}
            )
            for i, rc in enumerate(reversed_candidates)
        ]

    def warm_up(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_POLICY = """# Test Compliance Policy
**Version:** 3.2
**Effective Date:** 1 June 2025
**Owner:** MLRO
**Review Cycle:** Annual

---

## 1. Purpose

This policy defines the test requirements for customer onboarding and the evidence standards
that apply at each tier of review.

---

## 2. Identity Requirements

### 2.1 Passports

A passport is acceptable if valid or expired within the last 6 months. A passport issued more
than 10 years ago is not acceptable as a primary identity document under any circumstances.

### 2.2 Driving Licences

A photocard driving licence is acceptable where it remains valid at the time of submission.
Paper licences are not accepted. The licence must show the current residential address.

---

## 3. Escalation

Where documents cannot be verified to the required standard, the reviewing officer must
escalate the case to the MLRO before the client file progresses any further.
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings: every test gets its own data dir, database, and audit log."""
    return Settings(
        data_dir=tmp_path / "data",
        audit_log_path=tmp_path / "audit.log",
        llm_provider="groq",
        groq_api_key="test-key-not-real",
        rerank_enabled=False,
        retrieval_top_k=3,
        retrieval_candidate_pool=10,
        api_key=None,
        log_level="WARNING",
        evidence_refusal_floor=0.0,  # fake embedder scores differ from BGE; gate tested directly
    )


@pytest.fixture
def container(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AppContainer:
    """A fully wired container with fake models — no downloads, no network."""
    container = AppContainer(settings)
    fake_embedder = FakeEmbedder()
    container.__dict__["embedder"] = fake_embedder
    container.__dict__["reranker"] = __import__("app.rag.reranker", fromlist=["NoopReranker"]).NoopReranker()
    container.__dict__["_fake_llm"] = FakeLLM()
    monkeypatch.setattr(container, "provider_factory", lambda: container.__dict__["_fake_llm"])
    return container


@pytest.fixture
def fake_llm(container: AppContainer) -> FakeLLM:
    return container.__dict__["_fake_llm"]


@pytest.fixture
def indexed_container(container: AppContainer) -> AppContainer:
    """Container with one document already ingested."""
    container.document_service.upload(
        filename="test_compliance_policy.md", data=SAMPLE_POLICY.encode("utf-8")
    )
    return container


@pytest.fixture
def client(indexed_container: AppContainer):
    """TestClient wired to the fake-model container."""
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(indexed_container.settings, warm_models=False)

    # Replace the lifespan-built container with the fixture's fake-model one.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.container = indexed_container
        from app.core.security import RateLimiter

        app.state.rate_limiter = RateLimiter()
        yield

    app.router.lifespan_context = test_lifespan
    with TestClient(app) as test_client:
        yield test_client
