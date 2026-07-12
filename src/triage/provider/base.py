"""The provider-agnostic seam.

Everything downstream (agent, eval harness, memory) talks to `LLMProvider` and
receives a `NormalizedResponse` — never a vendor SDK object. That is what makes the
cross-model cost/quality table in Phase 3 trustworthy: cost, latency, and token
accounting are computed the *same way* here, in one place, regardless of who answered.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

# A chat message is a role + text. We only need the two conversational roles; the
# system prompt is passed separately (see `complete`) because vendors treat it
# differently on the wire — Anthropic has a dedicated `system` field, OpenAI-style
# APIs fold it in as a message with role "system". Normalizing that is an adapter job.
Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class NormalizedResponse:
    """The same shape no matter which provider answered."""

    text: str | None            # the model's text output (None if it only returned a tool call)
    input_tokens: int           # from the provider's usage block — the basis of the cost column
    output_tokens: int
    latency_ms: float           # wall-clock we measure around the call ourselves
    cost_usd: float             # tokens x this model's price (see pricing.py)
    finish_reason: str | None   # so a truncated answer is detectable, not scored as wrong
    model_version: str          # the exact model string the API returned (providers alias silently)
    provider: str               # "deepseek" | "anthropic"
    # The untouched vendor response, kept for debugging. `repr=False` so it doesn't
    # flood logs when we print a NormalizedResponse.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMProvider(ABC):
    """One method in, one normalized response out."""

    name: str

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.0,   # 0 for reproducibility; adapters guard models that reject it
        max_tokens: int = 1024,
    ) -> NormalizedResponse:
        """Send one request and return a normalized response.

        Tool calling (structured output) is deliberately NOT here yet — it arrives in
        Phase 2 where we actually use it, to avoid speculative code.
        """
        raise NotImplementedError
