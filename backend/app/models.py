"""Core domain models.

These are the vocabulary of the whole system — ingestion produces them, retrieval ranks
them, generation cites them, the API serialises them, the audit log records them. They are
Pydantic models (not dataclasses) so that every boundary crossing is validated, which is
what the original implementation did well and this version keeps.

Backward compatibility: `Chunk.document` / `Chunk.section` and the legacy `{document,
chunk}` citation shape are preserved so the original CLI contract and existing audit.log
readers keep working. New fields are additive only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["policy", "procedure", "guideline", "standard", "framework", "other"]
DocumentStatus = Literal["processing", "indexed", "failed", "inactive"]
EvidenceBand = Literal["strong", "moderate", "weak", "insufficient"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class ChunkMetadata(BaseModel):
    """Provenance for one retrievable unit.

    Every field is either genuinely parsed from the document or honestly null. In
    particular `page_start`/`page_end` are populated for PDF/DOCX only — markdown has no
    pages and we do not invent them.
    """

    model_config = ConfigDict(extra="ignore")

    document_id: str
    document_name: str
    document_title: str
    document_type: DocumentType = "other"
    version: str | None = None
    effective_date: date | None = None
    publication_date: date | None = None
    owner: str | None = None
    review_cycle: str | None = None
    section: str | None = None
    subsection: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    chunk_index: int = 0
    char_count: int = 0
    token_estimate: int = 0
    content_sha256: str = ""

    @property
    def citation_label(self) -> str:
        """Human-readable provenance, e.g.
        'Source of Wealth Verification Guidelines v1.3 — §3.1 Employment / Salary (p. 4)'.
        """
        parts = [self.document_title or self.document_name]
        if self.version:
            parts.append(f"v{self.version}")
        label = " ".join(parts)
        locus = self.subsection or self.section
        if locus:
            label = f"{label} — §{locus}"
        if self.page_start:
            page = (
                f"p. {self.page_start}"
                if self.page_end in (None, self.page_start)
                else f"pp. {self.page_start}–{self.page_end}"
            )
            label = f"{label} ({page})"
        return label

    @property
    def family_key(self) -> str:
        """Groups versions of the same document together for conflict detection."""
        return (self.document_title or self.document_name).strip().lower()


class Chunk(BaseModel):
    """A retrievable unit. `text` carries an inline provenance header so the LLM sees
    where the passage came from even if it ignores the surrounding structure."""

    chunk_uid: str
    faiss_id: int
    text: str
    metadata: ChunkMetadata

    # --- legacy accessors (original schema used flat `document` / `section`) ---
    @property
    def document(self) -> str:
        return self.metadata.document_name

    @property
    def section(self) -> str:
        return self.metadata.subsection or self.metadata.section or "(whole document)"


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float  # fused RRF score (or rerank score once reranking has run)
    rrf_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None

    @property
    def normalised_score(self) -> float:
        """Score on a 0–1 scale for evidence banding.

        RRF scores are tiny (1/(60+rank)) and cross-encoder logits are unbounded, so the
        two are mapped onto a comparable scale before thresholds are applied. This is a
        presentation transform, not a probability — see README DR-11.
        """
        if self.rerank_score is not None:
            # logistic squash of a cross-encoder logit
            x = max(-12.0, min(12.0, self.rerank_score))
            return 1.0 / (1.0 + pow(2.718281828459045, -x))
        # best achievable RRF score with both legs at rank 0 is 2/60 ≈ 0.0333
        return min(1.0, self.rrf_score / (2.0 / 60.0))


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """What the UI renders and what an auditor verifies.

    `document` and `chunk` are the original (v1) field names and are retained verbatim so
    the CLI's documented JSON contract still holds; everything else is additive.
    """

    document: str  # legacy: filename
    chunk: str  # legacy: passage text

    index: int = 1
    document_id: str = ""
    document_title: str = ""
    version: str | None = None
    effective_date: date | None = None
    section: str | None = None
    subsection: str | None = None
    page: int | None = None
    chunk_uid: str = ""
    label: str = ""
    retrieval_score: float | None = None
    rerank_score: float | None = None

    @classmethod
    def from_retrieved(cls, rc: RetrievedChunk, index: int) -> Citation:
        m = rc.chunk.metadata
        return cls(
            document=m.document_name,
            chunk=rc.chunk.text,
            index=index,
            document_id=m.document_id,
            document_title=m.document_title,
            version=m.version,
            effective_date=m.effective_date,
            section=m.section,
            subsection=m.subsection,
            page=m.page_start,
            chunk_uid=rc.chunk.chunk_uid,
            label=m.citation_label,
            retrieval_score=round(rc.score, 6),
            rerank_score=None if rc.rerank_score is None else round(rc.rerank_score, 4),
        )


class EvidenceSignals(BaseModel):
    top_score: float = 0.0
    score_margin: float = 0.0
    supporting_chunks: int = 0
    distinct_documents: int = 0
    cited_fraction_of_context: float = 0.0
    answer_is_refusal: bool = False


class Evidence(BaseModel):
    """Retrieval-derived evidence strength. Explicitly NOT a confidence probability —
    see README DR-11."""

    band: EvidenceBand = "insufficient"
    signals: EvidenceSignals = Field(default_factory=EvidenceSignals)
    basis: str = ""
    disclaimer: str = (
        "Derived from retrieval signals, not a calibrated probability. Always verify the cited passages."
    )


class ConflictingSource(BaseModel):
    document_id: str
    document_title: str
    document_name: str
    version: str | None = None
    effective_date: date | None = None
    section: str | None = None
    is_most_recent: bool = False


class Conflict(BaseModel):
    type: Literal["version_conflict"] = "version_conflict"
    description: str
    sources: list[ConflictingSource] = Field(default_factory=list)
    detection: Literal["structural"] = "structural"


class StageTimings(BaseModel):
    """Per-stage latency, surfaced in the response as well as the logs so a slow answer is
    attributable without reading a log file."""

    query_processing_ms: int = 0
    retrieval_ms: int = 0
    rerank_ms: int = 0
    context_ms: int = 0
    llm_ms: int = 0
    llm_ttft_ms: int | None = None
    validation_ms: int = 0
    total_ms: int = 0


class TokenUsage(BaseModel):
    """Null rather than estimated when the provider does not report usage (Ollama).
    A guessed token count in a cost dashboard is worse than no token count."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class RetrievalParams(BaseModel):
    """Recorded on every answer so an experiment can be reconstructed from its result."""

    top_k: int
    candidate_pool: int
    rrf_k: int
    rerank_enabled: bool
    rerank_model: str | None = None
    embedding_model: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    n_candidates: int = 0
    n_retrieved: int = 0
    n_dropped_duplicates: int = 0


class AnswerResult(BaseModel):
    """The full internal result of answering one question."""

    question: str
    rewritten_question: str | None = None
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)
    conflicts: list[Conflict] = Field(default_factory=list)
    refused: bool = False
    model: str = "unknown"
    timings: StageTimings = Field(default_factory=StageTimings)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    retrieval_params: RetrievalParams | None = None
    retrieved: list[RetrievedChunk] = Field(default_factory=list, exclude=True)
    request_id: str | None = None
    timestamp: str = Field(default_factory=utc_now_iso)
    error: str | None = None

    def to_legacy_response(self) -> QueryResponse:
        """The original CLI JSON contract: a superset, so old consumers still parse."""
        return QueryResponse(
            question=self.question,
            answer=self.answer,
            citations=self.citations,
            model=self.model,
            latency_ms=self.timings.total_ms,
            timestamp=self.timestamp,
            error=self.error,
            evidence=self.evidence,
            conflicts=self.conflicts,
            refused=self.refused,
        )


class QueryResponse(BaseModel):
    """Printed to stdout by the CLI `query` command. Field order and the original seven
    keys are unchanged; evidence/conflicts/refused are additive."""

    question: str
    answer: str
    citations: list[Citation]
    model: str
    latency_ms: int
    timestamp: str
    error: str | None = None
    evidence: Evidence | None = None
    conflicts: list[Conflict] = Field(default_factory=list)
    refused: bool = False


class LLMAnswer(BaseModel):
    """The JSON object the non-streaming path asks the model for. Citations are assembled
    by us from `used_chunk_ids` — never copied from model-authored text (README DR-4)."""

    answer: str
    used_chunk_ids: list[int] = Field(default_factory=list)
    conflict_note: str | None = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentRecord(BaseModel):
    id: str
    filename: str
    title: str
    doc_type: DocumentType = "other"
    version: str | None = None
    effective_date: date | None = None
    publication_date: date | None = None
    owner: str | None = None
    review_cycle: str | None = None
    status: DocumentStatus = "processing"
    content_sha256: str = ""
    byte_size: int = 0
    mime_type: str = ""
    page_count: int | None = None
    chunk_count: int = 0
    embedding_model: str | None = None
    uploaded_at: str = Field(default_factory=utc_now_iso)
    indexed_at: str | None = None
    failure_reason: str | None = None
    injection_flags: list[str] = Field(default_factory=list)
    family_key: str = ""
    tenant_id: str = "default"


class RetrievalFilters(BaseModel):
    """Applied *before* ranking. Post-hoc filtering would silently shrink k."""

    document_ids: list[str] | None = None
    doc_types: list[DocumentType] | None = None
    include_inactive: bool = False
    effective_from: date | None = None
    effective_to: date | None = None
    tenant_id: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(mode="json").items() if v not in (None, False)}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """One line in audit.log.

    The original five fields are unchanged so existing audit readers keep working. This log
    intentionally holds the full question and the full retrieved context: that is its
    regulatory purpose. Application logs hold a hash instead (see core/logging.py).
    """

    question: str
    response: QueryResponse
    retrieved_context: list[Chunk]
    model: str
    latency_ms: int
    timestamp: str
    error: str | None = None

    # additive
    request_id: str | None = None
    conversation_id: str | None = None
    rewritten_question: str | None = None
    retrieval_params: RetrievalParams | None = None
    evidence: Evidence | None = None
    token_usage: TokenUsage | None = None
    timings: StageTimings | None = None
