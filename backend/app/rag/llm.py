"""LLM provider abstraction.

Preserved from v1: the ABC with Groq (default, hosted) and Ollama (offline fallback)
implementations, a factory driven by one env var, and JSON-mode generation validated above
this layer. Added here:

  * `stream_text()` for the streaming chat path,
  * token-usage reporting, reported as None rather than estimated when a provider does not
    supply it (a guessed token count in a cost dashboard is worse than no count),
  * `health()` so the readiness endpoint can report provider status without a full call.

This layer stays a thin transport wrapper: schema validation and citation resolution happen
in the pipeline, which is what keeps providers interchangeable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from app.core.config import Settings
from app.core.errors import LLMError
from app.models import TokenUsage


class LLMProvider(ABC):
    model_name: str
    provider_name: str

    @abstractmethod
    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int, temperature: float = 0.0
    ) -> dict[str, Any]:
        """Return a parsed JSON object. Raises LLMError on transport or parse failure."""

    @abstractmethod
    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout: int,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> Iterator[str]:
        """Yield text deltas. Raises LLMError on transport failure."""

    @abstractmethod
    def health(self) -> tuple[bool, str]:
        """(reachable, detail) — cheap check for the readiness endpoint."""

    def last_usage(self) -> TokenUsage:
        return TokenUsage()


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


class GroqProvider(LLMProvider):
    provider_name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMError(
                "GROQ_API_KEY is not set. Add it to .env, or set LLM_PROVIDER=ollama to run fully offline."
            )
        try:
            from groq import Groq
        except ImportError as exc:
            raise LLMError("The groq package is not installed. Run: pip install groq") from exc
        self.client = Groq(api_key=api_key)
        self.model_name = model
        self._usage = TokenUsage()

    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int, temperature: float = 0.0
    ) -> dict[str, Any]:
        try:
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=timeout,
            )
        except Exception as exc:
            raise LLMError(f"Groq API error: {exc}") from exc

        self._capture_usage(completion)
        content = completion.choices[0].message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Groq returned content that is not JSON: {exc}") from exc

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout: int,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> Iterator[str]:
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                stream=True,
            )
        except Exception as exc:
            raise LLMError(f"Groq API error: {exc}") from exc

        try:
            for chunk in stream:
                # Groq reports usage on the terminal chunk, either directly or nested under
                # x_groq depending on SDK version. Both are checked; neither is estimated.
                self._capture_usage(chunk)
                x_groq = getattr(chunk, "x_groq", None)
                if x_groq is not None:
                    self._capture_usage(x_groq)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        except Exception as exc:
            raise LLMError(f"Groq stream failed: {exc}") from exc

    def health(self) -> tuple[bool, str]:
        return True, f"groq configured ({self.model_name})"

    def last_usage(self) -> TokenUsage:
        return self._usage

    def _capture_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        self._usage = TokenUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._usage = TokenUsage()

    def _payload(self, system_prompt: str, user_prompt: str, temperature: float, **extra: Any) -> dict:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": temperature},
            **extra,
        }

    def generate_json(
        self, system_prompt: str, user_prompt: str, *, timeout: int, temperature: float = 0.0
    ) -> dict[str, Any]:
        payload = self._payload(system_prompt, user_prompt, temperature, stream=False, format="json")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(f"Ollama is unreachable at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"Ollama returned a malformed envelope: {exc}") from exc

        self._capture_usage(data)
        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Ollama returned content that is not JSON: {exc}") from exc

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout: int,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> Iterator[str]:
        payload = self._payload(
            system_prompt,
            user_prompt,
            temperature,
            stream=True,
            options={"temperature": temperature, "num_predict": max_tokens},
        )
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = event.get("message", {}).get("content")
                    if piece:
                        yield piece
                    if event.get("done"):
                        self._capture_usage(event)
        except urllib.error.URLError as exc:
            raise LLMError(f"Ollama is unreachable at {self.base_url}: {exc}") from exc

    def health(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3) as response:
                json.loads(response.read().decode("utf-8"))
            return True, f"ollama reachable ({self.model_name})"
        except Exception as exc:
            return False, f"ollama unreachable at {self.base_url}: {exc}"

    def last_usage(self) -> TokenUsage:
        return self._usage

    def _capture_usage(self, data: dict[str, Any]) -> None:
        prompt = data.get("prompt_eval_count")
        completion = data.get("eval_count")
        total = (prompt or 0) + (completion or 0) if (prompt or completion) else None
        self._usage = TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


# ---------------------------------------------------------------------------


def build_provider(
    settings: Settings, *, provider: str | None = None, model: str | None = None
) -> LLMProvider:
    """Factory. `provider`/`model` allow a per-request override from the Settings page."""
    name = provider or settings.llm_provider
    if name == "groq":
        return GroqProvider(api_key=settings.groq_api_key or "", model=model or settings.groq_model)
    if name == "ollama":
        return OllamaProvider(base_url=settings.ollama_base_url, model=model or settings.ollama_model)
    raise LLMError(f"Unknown LLM provider: {name}")
