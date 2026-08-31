# Design — Usage Metering & Billing Engine

## 1. Schema

**tenants**
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| name | text | |
| created_at | timestamptz | |

**plans**
| column | type | notes |
|---|---|---|
| id | text, pk | `'free'` / `'pro'` — human-readable, not a surrogate int |
| api_call_limit | int | per billing period |
| ai_token_limit | int | per billing period |

Seeded by a data migration from the constants in `app/config.py` — config is still
the single source of truth for the numbers, the table exists so `subscriptions`
can FK to it and quota checks are a plain join, not a config lookup buried in
application code.

**subscriptions**
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| tenant_id | uuid, fk → tenants | |
| plan_id | text, fk → plans | |
| status | text | `active` / `past_due` / `canceled` |
| stripe_customer_id | text, nullable | |
| stripe_subscription_id | text, nullable, unique | |
| current_period_start | timestamptz | anchors the usage rollup window |
| current_period_end | timestamptz | |
| updated_at | timestamptz | |

**usage_events** — the idempotency guarantee lives here
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| tenant_id | uuid, fk → tenants | |
| idempotency_key | text | |
| usage_type | text | `api_call` / `ai_tokens` |
| quantity | int | call count, or total tokens for `ai_tokens` (used against `ai_token_limit`) |
| token_breakdown | jsonb, nullable | `{input, cached_input, output, reasoning}` — only set when `usage_type = 'ai_tokens'` |
| cost_cents | int | computed once at insert time and stored, so `/usage` is a `SUM`, not a recompute — pricing constants changing later can't silently reprice historical events |
| created_at | timestamptz | |

`UNIQUE (tenant_id, idempotency_key)` — this constraint, not an app-level
check-then-insert, is what makes "same request twice → one event" true under
concurrent retries.

**processed_events** — webhook dedupe, separate from usage on purpose (this is
Stripe-event state, not billable activity)
| column | type | notes |
|---|---|---|
| stripe_event_id | text, pk | |
| event_type | text | |
| processed_at | timestamptz | |

## 2. Plans & quotas

| Plan | API calls / mo | AI tokens / mo |
|---|---|---|
| Free | 1,000 | 100,000 |
| Pro | 10,000 *(placeholder — adjust and justify in README)* | 2,000,000 *(placeholder)* |

## 3. API contract

**POST /generate** — the one dummy billable endpoint
- Header: `Idempotency-Key: <string>` — required, 400 if missing.
- Body: `{ tenant_id, usage_type: "api_call" | "ai_tokens", token_breakdown?: {...} }`
- 200: `{ usage_event_id, quantity, cost_cents, cumulative_usage: {api_calls_used, ai_tokens_used}, quota: {api_call_limit, ai_token_limit} }`
- On a replayed idempotency key: same 200 body as the original call, plus a
  response header `Idempotent-Replay: true` so it's visible in a curl transcript
  without inspecting the DB.

**Idempotency strategy**: look up `(tenant_id, idempotency_key)` first; if found,
return the stored result. If not found, insert inside the same transaction as the
quota check — insert failing on the unique constraint (concurrent duplicate) is
treated the same as a cache hit, not an error.

**429 vs 402 — the exact rule, stated so it can be defended out loud:**
1. Is `subscriptions.status != active` for this tenant? → **402 Payment Required.**
   The plan itself doesn't currently entitle them to bill anything — this is a
   subscription problem, not a usage problem.
2. Else, would `usage_before + requested_quantity` exceed the plan's limit? →
   **429 Too Many Requests.** They have a valid plan, this request is over it.

**Boundary rule** (the "999 vs 1,000" question the brief asks explicitly):
a request is allowed when `usage_before + requested_quantity <= limit`. A tenant
at 999 used calls can make the 1,000th call — it lands exactly on the limit and
is allowed. The request that would make it 1,001 is rejected. The limit is
inclusive of the boundary value, not exclusive.

**GET /usage**
- 200: `{ plan: {code, api_call_limit, ai_token_limit}, period: {start, end}, usage: {api_calls_used, ai_tokens_used}, cost_cents_total }`

**POST /billing/checkout** — creates a Stripe test-mode Checkout session for
Free → Pro.

**POST /webhooks/stripe** — verifies signature, enqueues to Celery, returns 200
immediately. No plan/status mutation happens in the request path.

## 4. Non-goal

No proration in core. A mid-cycle Free → Pro upgrade takes effect immediately for
quota purposes (new limits apply right away), but the current period's cost is
not split or backdated. Proration is Section 9's stretch goal, not attempted
here.