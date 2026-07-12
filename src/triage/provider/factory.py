"""Pick a provider from the environment. `LLM_PROVIDER` chooses; per-provider model
strings default sensibly and can be overridden by env var."""

from __future__ import annotations

import os

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .deepseek import DeepSeekProvider


def get_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("LLM_PROVIDER", "deepseek")).lower()
    if name == "deepseek":
        return DeepSeekProvider(model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    if name == "anthropic":
        return AnthropicProvider(model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"))
    raise ValueError(f"Unknown LLM_PROVIDER: {name!r}. Expected 'deepseek' or 'anthropic'.")
