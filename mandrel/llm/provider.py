"""LLM provider interface and default Ollama implementation.

All LLM calls go through LLMProvider.complete(). The provider is pluggable:
swap MANDREL_LLM_BASE_URL to point at vLLM, OpenAI, or any compatible API.
Default target is Ollama (gemma4:26b) — no API key required, fully local.
"""

from __future__ import annotations

import json
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

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 600.0,
        reasoning_effort: str = "none",
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout = httpx.Timeout(connect=10.0, read=timeout_s, write=30.0, pool=10.0)
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def complete(
        self,
        messages: list[Message],
        *,
        on_token: Any = None,
        **kwargs: Any,
    ) -> str:
        """Stream the completion; return the full text.

        Streaming means the read timeout applies between chunks, not to the whole
        generation — a slow local model that is still producing tokens never times
        out, while a dead server still fails fast. `on_token(delta, total_chars)`
        is awaited for each content chunk when provided.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
            **kwargs,
        }
        if self.reasoning_effort:
            payload.setdefault("reasoning_effort", self.reasoning_effort)

        parts: list[str] = []
        total = 0
        reasoning_chars = 0
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise ValueError(
                    f"LLM request failed ({resp.status_code}) for model "
                    f"'{self.model}': {body[:500]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta_obj = choices[0].get("delta") or {}
                delta = delta_obj.get("content")
                if delta:
                    parts.append(delta)
                    total += len(delta)
                    if on_token is not None:
                        await on_token(delta, total)
                    continue
                # Reasoning models stream thinking separately; show it live
                # but never include it in the returned text.
                reasoning = delta_obj.get("reasoning")
                if reasoning:
                    reasoning_chars += len(reasoning)
                    if on_token is not None:
                        await on_token(reasoning, total)

        text = "".join(parts)
        if not text:
            if reasoning_chars:
                raise ValueError(
                    f"Model '{self.model}' produced {reasoning_chars} chars of "
                    "reasoning but no answer — the max_tokens budget was likely "
                    "consumed by thinking. Lower MANDREL_LLM_REASONING_EFFORT "
                    "(e.g. 'none') or raise max_tokens."
                )
            raise ValueError(
                f"LLM returned no content for model '{self.model}'. "
                "The model may have hit a context limit or produced an empty response."
            )
        return text

    async def aclose(self) -> None:
        await self._client.aclose()


def make_default_provider() -> OpenAICompatibleProvider:
    from mandrel.config import settings

    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_s=settings.llm_timeout_s,
        reasoning_effort=settings.llm_reasoning_effort,
    )
