from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A single retrievable unit. `text` already includes the Document/Section header."""

    chunk_id: int
    document: str
    section: str
    text: str


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float


class Citation(BaseModel):
    document: str
    chunk: str


class QueryResponse(BaseModel):
    """The single JSON object printed to stdout by `query`. Same shape on success or error."""

    question: str
    answer: str
    citations: list[Citation]
    model: str
    latency_ms: int
    timestamp: str
    error: Optional[str] = None


class LLMAnswer(BaseModel):
    """Internal: the JSON we ask the LLM to return. Citations are assembled by us from
    `used_chunk_ids`, never copied from free text the model wrote."""

    answer: str
    used_chunk_ids: list[int] = Field(default_factory=list)


class AuditEntry(BaseModel):
    """One line in audit.log. Captures everything needed to reconstruct a query."""

    question: str
    response: QueryResponse
    retrieved_context: list[Chunk]
    model: str
    latency_ms: int
    timestamp: str
    error: Optional[str] = None
