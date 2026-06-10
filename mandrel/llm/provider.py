"""LLM provider interface and default Ollama implementation.

All LLM calls go through LLMProvider.complete(). The provider is pluggable:
swap MANDREL_LLM_BASE_URL to point at vLLM, OpenAI, or any compatible API.
Default target is Ollama (gemma4:26b) — no API key required, fully local.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel


class Message(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, messages: list[Message], **kwargs: Any) -> str:
        """Send a chat completion request; return the assistant's text."""
        ...


class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions (works with Ollama, vLLM, OpenAI).

    Default: Ollama at http://localhost:11434/v1 with gemma4:26b.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120.0)
        self.model = model

    async def complete(self, messages: list[Message], **kwargs: Any) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            **kwargs,
        }
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        if content is None:
            raise ValueError(
                f"LLM returned null content for model '{self.model}'. "
                "The model may have hit a context limit or produced an empty response."
            )
        return content

    async def aclose(self) -> None:
        await self._client.aclose()


def make_default_provider() -> OpenAICompatibleProvider:
    from mandrel.config import settings

    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
