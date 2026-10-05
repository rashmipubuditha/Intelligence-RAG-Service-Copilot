from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: Literal["groq", "ollama"] = "groq"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b-instruct"

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    vector_store_dir: Path = Path("./data")

    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2

    @property
    def active_model_name(self) -> str:
        return self.groq_model if self.llm_provider == "groq" else self.ollama_model


def get_settings() -> Settings:
    return Settings()
