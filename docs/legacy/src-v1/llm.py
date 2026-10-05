"""LLM provider abstraction.

Two providers in scope:
  - Groq (default): hosted Llama 3.3 70B with native JSON mode.
  - Ollama (fallback): local Llama 3.1 8B for fully-offline runs.

Both expose the same `generate_json` method which returns a parsed dict. Schema validation
into LLMAnswer happens in the query orchestrator, not here, so this layer stays a thin
transport wrapper.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from src.config import Settings


class LLMError(Exception):
    """Any failure to obtain a parseable JSON response from the LLM."""


class LLMProvider(ABC):
    model_name: str

    @abstractmethod
    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int
    ) -> dict[str, Any]:
        """Return the parsed JSON object. Raises LLMError on transport or parse failure."""


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError(
                "GROQ_API_KEY is missing. Set it in .env or switch LLM_PROVIDER=ollama."
            )
        try:
            from groq import Groq
        except ImportError as e:
            raise LLMError("groq package not installed. Run: pip install groq") from e
        self.client = Groq(api_key=api_key)
        self.model_name = model

    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int
    ) -> dict[str, Any]:
        try:
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as e:
            raise LLMError(f"Groq API error: {e}") from e

        content = completion.choices[0].message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Groq returned non-JSON content: {e}; raw={content!r}") from e


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model_name = model

    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int
    ) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise LLMError(f"Ollama unreachable at {self.base_url}: {e}") from e
        except json.JSONDecodeError as e:
            raise LLMError(f"Ollama returned malformed envelope: {e}") from e

        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Ollama returned non-JSON content: {e}; raw={content!r}") from e


def build_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "groq":
        return GroqProvider(api_key=settings.groq_api_key or "", model=settings.groq_model)
    if provider == "ollama":
        return OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
    raise LLMError(f"Unknown LLM provider: {provider}")
