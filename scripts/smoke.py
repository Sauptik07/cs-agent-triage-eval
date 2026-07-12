"""One call through the abstraction, printing the normalized result.

Run it:  uv run python scripts/smoke.py
Choose the provider by setting LLM_PROVIDER=deepseek|anthropic in your .env.
"""

from __future__ import annotations

from dotenv import load_dotenv

# Load .env before importing anything that reads API keys.
load_dotenv()

from triage.provider import Message, get_provider, is_priced  # noqa: E402


def main() -> None:
    provider = get_provider()
    resp = provider.complete(
        messages=[Message("user", "In one sentence, what is support-ticket triage?")],
        system="You are a concise assistant. Answer in one sentence.",
    )

    print(f"provider       : {resp.provider}")
    print(f"model_version  : {resp.model_version}")
    print(f"finish_reason  : {resp.finish_reason}")
    print(f"latency_ms     : {resp.latency_ms:.0f}")
    print(f"input_tokens   : {resp.input_tokens}")
    print(f"output_tokens  : {resp.output_tokens}")
    cost_note = "" if is_priced(getattr(provider, "model", "")) else "  (model not in price table!)"
    print(f"cost_usd       : ${resp.cost_usd:.6f}{cost_note}")
    print(f"text           : {resp.text}")


if __name__ == "__main__":
    main()
