from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AgentUsage:
    requests: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int


_MODEL_PRICING_PER_MILLION: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "gpt-5-mini": (Decimal("0.25"), Decimal("0.025"), Decimal("2.00")),
}
_ONE_MILLION = Decimal(1_000_000)


def _non_negative_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def extract_run_usage(run_result: Any) -> AgentUsage:
    """Extract usage reported by the context wrapper for one Runner.run call."""
    usage = run_result.context_wrapper.usage
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return AgentUsage(
        requests=_non_negative_int(getattr(usage, "requests", 0)),
        input_tokens=_non_negative_int(getattr(usage, "input_tokens", 0)),
        cached_input_tokens=_non_negative_int(
            getattr(input_details, "cached_tokens", 0) if input_details is not None else 0
        ),
        output_tokens=_non_negative_int(getattr(usage, "output_tokens", 0)),
        reasoning_tokens=_non_negative_int(
            getattr(output_details, "reasoning_tokens", 0) if output_details is not None else 0
        ),
        total_tokens=_non_negative_int(getattr(usage, "total_tokens", 0)),
    )


def estimate_cost_usd(model_name: str, usage: AgentUsage) -> Decimal | None:
    pricing = _MODEL_PRICING_PER_MILLION.get(model_name)
    if pricing is None:
        return None
    input_rate, cached_input_rate, output_rate = pricing
    uncached_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    return (
        Decimal(uncached_input) * input_rate
        + Decimal(usage.cached_input_tokens) * cached_input_rate
        + Decimal(usage.output_tokens) * output_rate
    ) / _ONE_MILLION
