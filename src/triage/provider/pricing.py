"""The price table. Every cost number in the eval is arithmetic on these values,
so a wrong entry silently corrupts the whole cost column — keep it honest and dated.

Prices are USD per 1,000,000 tokens (the industry-standard unit).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


# Last checked: 2026-07-12.
# Anthropic values confirmed against the current models/pricing reference.
# DeepSeek values are the published deepseek-chat (cache-miss) rates — VERIFY against
# https://api-docs.deepseek.com/quick_start/pricing before trusting the cost column,
# as DeepSeek adjusts these and applies cache-hit discounts we do not model here.
PRICES: dict[str, Price] = {
    # Anthropic
    "claude-haiku-4-5": Price(1.00, 5.00),
    "claude-sonnet-5": Price(3.00, 15.00),
    "claude-opus-4-8": Price(5.00, 25.00),
    # DeepSeek (verify — see note above)
    "deepseek-chat": Price(0.27, 1.10),
    "deepseek-reasoner": Price(0.55, 2.19),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost in USD for one call. Priced against the model we *requested* (which we
    control and which matches the table); the returned model_version is recorded
    separately for the run record. Unknown model -> 0.0 with a visible marker in the
    caller's output rather than a crash, so a missing price never aborts an eval run.
    """
    price = PRICES.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens / 1_000_000 * price.input_per_mtok
        + output_tokens / 1_000_000 * price.output_per_mtok
    )


def is_priced(model: str) -> bool:
    return model in PRICES
