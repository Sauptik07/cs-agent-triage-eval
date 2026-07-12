"""DeepSeek adapter — raw HTTP, so you can see exactly what goes over the wire.

DeepSeek exposes an OpenAI-compatible Chat Completions API. We POST JSON directly with
httpx (no vendor SDK) because seeing the raw request/response is the point of Phase 0.
The system prompt is folded in as a message with role "system" — that's the OpenAI-style
convention, and normalizing it here is exactly the adapter's job.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from .base import LLMProvider, Message, NormalizedResponse
from .pricing import estimate_cost


class DeepSeekProvider(LLMProvider):
    name = "deepseek"
    BASE_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Copy .env.example to .env and fill it in."
            )

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> NormalizedResponse:
        # Build the messages array the OpenAI/DeepSeek way: system (if any) first,
        # then the conversation. The API is stateless — the whole list IS the context.
        wire_messages: list[dict[str, str]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        wire_messages.extend({"role": m.role, "content": m.content} for m in messages)

        body: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        start = time.perf_counter()
        response = httpx.post(self.BASE_URL, headers=headers, json=body, timeout=60.0)
        latency_ms = (time.perf_counter() - start) * 1000
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        usage = data["usage"]  # OpenAI-shape: prompt_tokens / completion_tokens
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]

        return NormalizedResponse(
            text=choice["message"]["content"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
            finish_reason=choice.get("finish_reason"),
            model_version=data.get("model", self.model),
            provider=self.name,
            raw=data,
        )
