"""Application settings.

All configuration arrives through environment variables / .env — nothing is hardcoded and
no secret is ever defaulted to a real value. Settings are grouped by concern but kept on a
single flat object because pydantic-settings maps env vars to flat fields, and a flat object
is what dependency injection needs to pass around.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["groq", "ollama"] = "groq"
    groq_api_key: str | None = None
    # v1 defaulted to llama-3.3-70b-versatile, which Groq has since decommissioned (404
    # model_not_found). Swapping the default was a one-line change precisely because the
    # provider abstraction keeps the model out of the pipeline — see README DR-3.
    groq_model: str = "openai/gpt-oss-120b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b-instruct"
    llm_timeout_seconds: int = 60
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_max_answer_tokens: int = Field(default=1200, ge=128, le=8192)

    # --- embeddings --------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages:"
    embedding_batch_size: int = Field(default=32, ge=1, le=256)

    # --- retrieval ---------------------------------------------------------
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    retrieval_candidate_pool: int = Field(default=30, ge=5, le=200)
    rrf_k: int = Field(default=60, ge=1)
    rrf_dense_weight: float = Field(default=1.0, ge=0.0)
    rrf_sparse_weight: float = Field(default=1.0, ge=0.0)
    context_max_tokens: int = Field(default=3000, ge=500, le=16000)
    dedup_similarity_threshold: float = Field(default=0.97, ge=0.5, le=1.0)

    # --- reranking ---------------------------------------------------------
    # Enabled by default because the golden set says so (README DR-7): recall@1 0.774 → 0.870,
    # MRR 0.776 → 0.863, nDCG@5 0.781 → 0.845. top_n=10 rather than 30 because reranking the
    # fused top-10 measured *identical* quality to reranking 30 at a quarter of the latency
    # (566 ms p50 vs 2216 ms p50 on CPU).
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_top_n: int = Field(default=10, ge=5, le=200)

    # --- evidence bands ----------------------------------------------------
    evidence_refusal_floor: float = 0.30
    evidence_moderate_floor: float = 0.45
    evidence_strong_floor: float = 0.60

    # --- storage -----------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    audit_log_path: Path = PROJECT_ROOT / "audit.log"

    # --- uploads -----------------------------------------------------------
    max_upload_bytes: int = 20 * 1024 * 1024
    max_upload_files: int = 10
    max_pdf_pages: int = 500

    # --- server / security -------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    api_key: str | None = None
    api_key_role: Literal["viewer", "analyst", "admin"] = "admin"
    # Public demo mode: callers without a key are read-only viewers (ask questions, browse
    # documents) instead of being rejected; writes still need API_KEY. With no API_KEY set
    # nobody can write, so a forgotten secret fails closed rather than open.
    public_read: bool = False
    # Origins allowed to embed the UI in a frame (space-separated CSP sources). Unset keeps
    # the default X-Frame-Options: DENY.
    frame_ancestors: str | None = None
    # Built SPA to serve from this process (single-container deployments). Unset means the
    # UI is served elsewhere — nginx in Compose, Vite in development.
    static_dir: Path | None = None
    rate_limit_per_minute: int = Field(default=60, ge=1)
    rate_limit_upload_per_minute: int = Field(default=10, ge=1)
    max_question_chars: int = Field(default=4000, ge=16)

    # --- observability -----------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    log_questions: bool = False

    @field_validator("data_dir", "audit_log_path", mode="after")
    @classmethod
    def _absolutise(cls, v: Path) -> Path:
        return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()

    # --- derived -----------------------------------------------------------
    @property
    def active_model_name(self) -> str:
        return self.groq_model if self.llm_provider == "groq" else self.ollama_model

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key) or self.public_read

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.index_dir, self.uploads_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached so the whole process shares one settings object (and one .env read)."""
    return Settings()
