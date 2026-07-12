"""Anthropic adapter — uses the official `anthropic` SDK (the documented, supported path).

The SDK gives us typed responses and built-in retries; we still measure wall-clock latency
ourselves and normalize the usage/cost the same way as every other provider.
"""

from __future__ import annotations

import os
import time
from typing import Any

import anthropic

from .base import LLMProvider, Message, NormalizedResponse
from .pricing import estimate_cost

# The current frontier models REJECT the `temperature` parameter with an HTTP 400
# (sampling params were removed on these). Haiku 4.5 — our intended Anthropic model —
# still accepts it, so temperature=0 works there. This guard means the abstraction
# won't blow up if someone points ANTHROPIC_MODEL at a frontier model: we simply omit
# temperature (those models are already near-deterministic). This is precisely the kind
# of vendor quirk the adapter exists to hide from everything downstream.
_TEMPERATURE_UNSUPPORTED = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-fable-5",
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-haiku-4-5", api_key: str | None = None) -> None:
        self.model = model
        # The SDK reads ANTHROPIC_API_KEY from the environment when api_key is None.
        if not (api_key or os.environ.get("ANTHROPIC_API_KEY")):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> NormalizedResponse:
        # Anthropic keeps the system prompt in its own top-level field, not in `messages`.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system:
            kwargs["system"] = system
        if not self.model.startswith(_TEMPERATURE_UNSUPPORTED):
            kwargs["temperature"] = temperature

        start = time.perf_counter()
        resp = self.client.messages.create(**kwargs)
        latency_ms = (time.perf_counter() - start) * 1000

        # content is a list of blocks; pull the first text block.
        text = next((b.text for b in resp.content if b.type == "text"), None)
        input_tokens = resp.usage.input_tokens
        output_tokens = resp.usage.output_tokens

        return NormalizedResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
            finish_reason=resp.stop_reason,
            model_version=resp.model,
            provider=self.name,
            raw=resp.model_dump(),
        )
