### Phase 1 — Design
- **AI helped:** drafted the one-page design doc (schema, plans, `POST /generate` contract,
  idempotency strategy, non-goal). I reviewed and confirmed the numbers before committing.

### Phase 2 — Core metering & quotas
- **AI helped:** generated the SQLAlchemy models (tenants, plans, usage_events,
  monthly_rollups), the layered repo/service split, and the idempotency + quota logic.
- **AI was wrong / I caught:**
  - The first cut checked idempotency by `(idempotency_key, event_type)` while the DB
    unique constraint is `(tenant_id, idempotency_key)`. Sending the **same key with a
    different event_type** slipped past the check and raised a `500` (IntegrityError).
  - **Fix I applied:** lookup by `(tenant_id, idempotency_key)` only (matches the
    constraint), plus a race-safety net that catches `IntegrityError` and returns the
    original event instead of a 500. Verified: same key + different type now returns
    `is_duplicate: true` and one row.
- **AI was wrong / I caught:**
  - `app/services.py` (flat module) and `app/services/` (package) both existed —
    Python collision. I deleted the stale flat `services.py`; all imports use the package.

### Phase 3 — Stripe integration + background job
- **AI helped:** built the checkout session creation, signature verification, and the
  Celery worker to move webhook processing off the request path.
- **AI was wrong / I caught:**
  - The webhook router passed `event["data"]` to the worker, but the service read
    `payload["data"]["object"]` — double-nesting meant the object came through empty,
    so a completed checkout reported "Missing tenant_id" and never flipped the plan.
  - **Fix I applied:** router now passes the full event; service reads the object correctly.
- **AI was wrong / I caught:**
  - `seed.py` hardcoded `stripe_price_id="price_pro_tier"` (a placeholder, not a live
    Stripe Price ID). Creating a Checkout session with it returned
    `No such price: 'price_pro_tier'`.
  - **Fix I applied:** checkout now prefers the configured real price from `.env`
    (`STRIPE_PRICE_PRO_ID`) over the DB placeholder. Verified: returned a real
    `cs_test_...` session URL with correct `tenant_id` metadata.
- **Realization (not a bug):** `/api/v1/generate` meters usage locally; it does **not**
  create Stripe charges. That's by design — the brief meters simulated numbers and uses
  Stripe only for subscription payments (Checkout → webhook → plan sync). Metered calls
  are not expected to appear as Stripe charges.

### Phase 4 — Cost & finalization
- **AI helped:** pinned the integer-cents pricing constants and the token pricing rules
  (cached < fresh; reasoning = output).
- **AI was wrong / I caught:**
  - `cost_service` returned a hardcoded `total_cost_cents: 0` — `/usage` showed no cost.
  - **Fix I applied:** added a repo query summing `usage_events.cost_cents` for the month.
    Verified: 1000 input tokens = 1¢ + 3000 output = 9¢ → `/usage` shows `total_cost_cents: 10`.