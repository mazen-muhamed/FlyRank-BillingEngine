# Phase 4 — Cost calculator
# Rules (per DESIGN.md): cached input cheaper; reasoning = output pricing; categories NOT summed flat.

API_CALL_CENT = 1      # 1000 calls = $0.01 → 1 cent each 
INPUT_CENT_PER_1K = 3   # cached cheaper: 2 / fresh: 3 per 1k tokens
CACHED_INPUT_CENT_PER_1K = 2
OUTPUT_CENT_PER_1K = 8  # reasoning counted HERE (as output) — one line, can't miss it

def calc_cost(api_calls: int, input_tokens: int, cached: int, output_tokens: int, reasoning: int) -> int:
    total = 0
    total += api_calls * API_CALL_CENT
    total += (input_tokens // 1000) * INPUT_CENT_PER_1K
    total += (cached // 1000) * CACHED_INPUT_CENT_PER_1K
    total += ((output_tokens + reasoning) // 1000) * OUTPUT_CENT_PER_1K
    return total
