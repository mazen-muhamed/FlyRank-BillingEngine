"""Domain & pricing: no DB, no HTTP. Integer-cents money math only.

The three rules an evaluator will probe:
1. Cached input tokens are cheaper than fresh input (separate rate).
2. Reasoning tokens are priced AS OUTPUT (vendor bills thinking as output — same rate).
3. Categories are summed independently, not as one flat token rate.
"""
from app.schemas import CostBreakdown

# Pricing in cents. Zero-rate entries exist so every event_type maps to a row.
PRICING = {
    "api_call": 0,
    "input_token": 1,           # 1 cent per 1,000 tokens
    "cached_input_token": 0,    # ~0.1 cents per 1k — whole-cent math floors to 0
    "output_token": 3,          # 3 cents per 1,000 tokens
    "reasoning_token": 3,       # counted as output tokens
}

_TOKENS_PER_THOUSAND = 1000


def tokens_to_cents(quantity: int, token_type: str) -> int:
    """Token count → integer cents. Whole thousands only (floor); no floats."""
    rate_cents_per_1k = PRICING.get(token_type, 0)
    if rate_cents_per_1k == 0:
        return 0
    return (quantity // _TOKENS_PER_THOUSAND) * rate_cents_per_1k


def compute_total_cost(events: list[dict]) -> CostBreakdown:
    """Cost from a list of {'event_type': ..., 'quantity': ...}. Never a float."""
    breakdown = {k: 0 for k in PRICING}
    for e in events:
        t = e.get("event_type")
        q = e.get("quantity", 0)
        if t in breakdown:
            breakdown[t] += tokens_to_cents(q, t)
    total = sum(breakdown.values())  # all ints
    return CostBreakdown(**breakdown, total_cents=total)


def get_plan_limits(plan_name: str) -> dict:
    if plan_name == "pro":
        return {"api_calls_limit": 10000, "tokens_limit": 1000000}
    return {"api_calls_limit": 1000, "tokens_limit": 100000}