"""API request/response models.

Separate from the domain models in app/models.py on purpose: the HTTP contract should be able
to evolve (add a field, rename for clarity, paginate) without forcing a change to the internal
vocabulary of the RAG pipeline, and vice versa. Examples are attached so /docs is usable as
the API documentation deliverable rather than a bare schema dump.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from app.models import Citation, Conflict, DocumentType, Evidence, StageTimings, TokenUsage
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str = Field(examples=["validation_error"])
    message: str = Field(examples=["The question is required."])
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    timestamp: str


class ErrorResponse(BaseModel):
    """Every non-2xx response in this API has this shape."""

    error: ErrorBody


class Page(BaseModel):
    limit: int
    offset: int
    total: int
    returned: int


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class RetrievalFilterRequest(BaseModel):
    document_ids: list[str] | None = Field(default=None, description="Restrict retrieval to these documents.")
    doc_types: list[DocumentType] | None = None
    include_inactive: bool = Field(
        default=False,
        description="Include deactivated/superseded documents. Off by default so a "
        "superseded policy is never returned as a current rule.",
    )
    effective_from: date | None = None
    effective_to: date | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What are the KYC requirements for high-risk customers?",
                "k": 5,
            }
        }
    )

    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, description="Omit to start a new conversation.")
    k: int | None = Field(default=None, ge=1, le=20, description="Passages to retrieve.")
    filters: RetrievalFilterRequest | None = None
    use_history: bool = Field(
        default=True, description="Use conversation history to rewrite follow-up questions."
    )

    @field_validator("question")
    @classmethod
    def _question_must_have_content(cls, value: str) -> str:
        """A whitespace-only question is a client error, so it is rejected at the HTTP
        boundary with 422 rather than travelling into the pipeline and coming back as a
        200 carrying an error field."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("The question cannot be empty or whitespace only.")
        return cleaned


class ChatResponse(BaseModel):
    """A superset of the v1 CLI response: the original seven fields are unchanged."""

    question: str
    rewritten_question: str | None = None
    answer: str
    citations: list[Citation]
    evidence: Evidence
    conflicts: list[Conflict] = Field(default_factory=list)
    refused: bool
    model: str
    conversation_id: str
    latency_ms: int
    timings: StageTimings
    token_usage: TokenUsage
    retrieval: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    timestamp: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentResponse(BaseModel):
    id: str
    filename: str
    title: str
    doc_type: DocumentType
    version: str | None = None
    effective_date: date | None = None
    publication_date: date | None = None
    owner: str | None = None
    review_cycle: str | None = None
    status: str
    chunk_count: int
    page_count: int | None = None
    byte_size: int
    mime_type: str
    embedding_model: str | None = None
    uploaded_at: str
    indexed_at: str | None = None
    failure_reason: str | None = None
    injection_flags: list[str] = Field(
        default_factory=list,
        description="Spans that look like prompt injection. Flagged for human review; "
        "answers are protected structurally regardless (see README §17).",
    )
    content_sha256: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    page: Page


class UploadedDocument(BaseModel):
    document: DocumentResponse
    chunks: int
    duplicate_of: str | None = Field(
        default=None,
        description="Set when identical content was already indexed; no duplicate was created.",
    )
    elapsed_ms: int


class UploadFailure(BaseModel):
    """A per-file rejection. Typed rather than a free-form dict so the frontend can render
    it without casting — the same reason StatsResponse is typed."""

    file: str
    code: str = "ingest_failed"
    error: str


class UploadResponse(BaseModel):
    uploaded: list[UploadedDocument]
    failed: list[UploadFailure] = Field(default_factory=list)


class ChunkResponse(BaseModel):
    chunk_uid: str
    chunk_index: int
    section: str | None = None
    subsection: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    char_count: int
    token_estimate: int
    text: str
    label: str


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    page: Page


class SectionNode(BaseModel):
    section: str
    subsections: list[str] = Field(default_factory=list)
    chunk_count: int
    pages: list[int] | None = None


class DocumentDetailResponse(BaseModel):
    document: DocumentResponse
    sections: list[SectionNode]
    chunk_preview: list[ChunkResponse]


class DocumentPatchRequest(BaseModel):
    status: Literal["indexed", "inactive"] | None = Field(
        default=None, description="'indexed' activates, 'inactive' excludes from retrieval."
    )
    title: str | None = None
    doc_type: DocumentType | None = None
    version: str | None = None
    effective_date: date | None = None


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    page: Page


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    model: str | None = None
    citations: list[dict[str, Any]] | None = None
    evidence: dict[str, Any] | None = None
    conflicts: list[dict[str, Any]] | None = None
    timings: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None
    refused: bool = False
    error: str | None = None


class ConversationDetailResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    messages: list[MessageResponse]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"dataset": "aml_kyc_golden_v1", "mode": "retrieval_only"}}
    )

    dataset: str = "aml_kyc_golden_v1"
    mode: Literal["retrieval_only", "full"] = Field(
        default="retrieval_only",
        description="retrieval_only is deterministic and needs no LLM; full adds generation.",
    )
    top_k: int | None = Field(default=None, ge=1, le=20)
    rerank: bool | None = None
    judge: bool = Field(default=False, description="Add LLM-judged faithfulness/relevance (full mode only).")
    limit: int | None = Field(default=None, ge=1)
    categories: list[str] | None = None


class EvaluationRunSummary(BaseModel):
    id: str
    dataset: str
    mode: str
    status: str
    started_at: str
    finished_at: str | None = None
    n_questions: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EvaluationRunDetail(EvaluationRunSummary):
    results: list[dict[str, Any]] = Field(default_factory=list)


class EvaluationStartedResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    message: str
    poll: str = Field(description="Poll GET /api/evaluation/runs for completion.")


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


class DocumentCounts(BaseModel):
    total: int = 0
    active: int = 0
    processing: int = 0
    failed: int = 0
    inactive: int = 0


class IndexStats(BaseModel):
    chunks: int = 0
    vectors: int = 0
    bm25_documents: int = 0
    embedding_model: str | None = None
    embedding_dim: int | None = None
    in_sync: bool = True


class QueryStats(BaseModel):
    queries_total: int = 0
    refusals: int = 0
    errors: int = 0
    avg_total_ms: int = 0
    avg_retrieval_ms: int = 0
    avg_llm_ms: int = 0
    p50_total_ms: int = 0
    p95_total_ms: int = 0
    refusal_rate: float = 0.0
    error_rate: float = 0.0


class RetrievalConfigStats(BaseModel):
    top_k: int
    candidate_pool: int
    rrf_k: int
    rerank_enabled: bool
    rerank_model: str | None = None


class ActivityEntry(BaseModel):
    """Analytics only — a question hash, never the question text (see README §16)."""

    created_at: str
    question_hash: str
    question_len: int
    model: str | None = None
    n_cited: int = 0
    evidence_band: str | None = None
    refused: bool = False
    total_ms: int = 0
    error_code: str | None = None


class LatestEvaluation(BaseModel):
    id: str
    dataset: str
    mode: str
    status: str
    started_at: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    """Dashboard aggregates.

    Fully typed rather than a bare dict so the generated frontend types are usable: an
    untyped `dict[str, Any]` here becomes `Record<string, unknown>` in TypeScript, which
    pushes every field access back to runtime. Typing it means a renamed field breaks the
    build instead of the dashboard.
    """

    documents: DocumentCounts
    index: IndexStats
    queries: QueryStats
    retrieval: RetrievalConfigStats
    conversations: dict[str, int] = Field(default_factory=dict)
    recent_activity: list[ActivityEntry] = Field(default_factory=list)
    evaluation: dict[str, LatestEvaluation | None] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class ReadinessResponse(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]


class SettingsResponse(BaseModel):
    """Secrets are never returned — only whether they are configured."""

    llm_provider: str
    llm_model: str
    groq_configured: bool
    ollama_base_url: str
    embedding_model: str
    embedding_query_prefix_enabled: bool
    retrieval_top_k: int
    retrieval_candidate_pool: int
    rrf_k: int
    rerank_enabled: bool
    rerank_model: str
    temperature: float
    context_max_tokens: int
    evidence_floors: dict[str, float]
    auth_enabled: bool
    rate_limit_per_minute: int
    max_upload_mb: float
    allowed_file_types: list[str]


class SettingsPatchRequest(BaseModel):
    """Session-scoped overrides — never written to disk."""

    llm_provider: Literal["groq", "ollama"] | None = None
    llm_model: str | None = Field(default=None, max_length=120)
    top_k: int | None = Field(default=None, ge=1, le=20)
    rerank_enabled: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
