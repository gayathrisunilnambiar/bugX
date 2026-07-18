"""Explicitly disclosed structural cost estimates for analysis attempts."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

# Verified 2026-07-18 against https://developers.openai.com/api/docs/models/gpt-5.6-sol
# These are the uncached GPT-5.6 Sol API prices per one million tokens.
GPT_56_SOL_INPUT_USD_PER_MILLION = 5.00
GPT_56_SOL_OUTPUT_USD_PER_MILLION = 30.00
GPT_56_SOL_PRICING_SOURCE = "https://developers.openai.com/api/docs/models/gpt-5.6-sol"
COST_ESTIMATE_DISCLOSURE = (
    "ESTIMATED from published GPT-5.6 Sol pricing and structural character-based token estimates; "
    "no live GPT-5.6 API call has been made; not a measured cost."
)


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "estimated_input_tokens": self.input_tokens,
            "estimated_output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_cost_disclosure": COST_ESTIMATE_DISCLOSURE,
            "pricing_source": GPT_56_SOL_PRICING_SOURCE,
        }


def structural_token_estimate(text: str) -> int:
    """A transparent 4-characters-per-token structural estimate, never a measurement."""
    return ceil(len(text) / 4)


def estimate_gpt_56_sol_cost(input_text: str, output_text: str) -> CostEstimate:
    input_tokens = structural_token_estimate(input_text)
    output_tokens = structural_token_estimate(output_text)
    cost = (
        input_tokens * GPT_56_SOL_INPUT_USD_PER_MILLION
        + output_tokens * GPT_56_SOL_OUTPUT_USD_PER_MILLION
    ) / 1_000_000
    return CostEstimate(input_tokens, output_tokens, cost)
