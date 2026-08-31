# EVIDENCE — proof per requirement

Each box below maps to a Requirement in Section 6 of the capstone brief. Proof is a
real transcript captured from the running system (FastAPI + Postgres + Celery + Redis).

Stack running: `uvicorn app.main:app` on `:8000`, Postgres `billing` db, Redis, Celery worker.

---

## 1. Metering — exactly-once usage (idempotency)

**Proof — the same request sent twice creates one usage event; the retry mirrors the original.**

```
$ curl -s -X POST localhost:8000/api/v1/generate -H 'Content-Type: application/json' \
    -d '{"idempotency_key":"e2e-1","event_type":"api_call","quantity":7}'
{"event_id":"931e4455-fb44-4d13-ae11-83fee180c679","quantity":7,"is_duplicate":false}

$ curl -s -X POST localhost:8000/api/v1/generate -H 'Content-Type: application/json' \
    -d '{"idempotency_key":"e2e-1","event_type":"api_call","quantity":999}'
{"event_id":"931e4455-fb44-4d13-ae11-83fee180c679","quantity":7,"is_duplicate":true}
                                            ^^^^^^^^^                                  ^^^^
                                            SAME event id                            dup flag
```

DB count for the key (must be 1 — no double-count):
```
$ psql -d billing -c "select count(*) from usage_events where idempotency_key='e2e-1';"
 count
-------
     1
```
**Guarantee:** retries return the original event; the DB `UNIQUE(tenant_id, idempotency_key)` is the race-proof guard, not the app-level check.

---

## 2. Quota enforcement — correct status codes

The quota is checked **before** the action. At the boundary:
- Over the Free plan's monthly limit → **429 Too Many Requests** + clear message.
- Plan lapsed/canceled → **402 Payment Required**.

(Full boundary transcript: 1,001st `api_call` against a 1,000 limit returns `429`.)

---

## 3. Cost calculation — integer cents, correct token rules

**Pricing constants (pinned in `app/billing.py`, exposed via `/api/v1/cost-breakdown`):**
```
$ curl -s localhost:8000/api/v1/cost-breakdown
{"api_call":0,"input_token":1,"cached_input_token":0,"output_token":3,"reasoning_token":3,"total_cents":0}
```
- **cached input (0) is cheaper than fresh input (1)** ✓
- **reasoning (3) priced as output (3)** — not a separate free category ✓

**Cost rollup matches pinned math (integer cents):**
```
$ curl -s -X POST localhost:8000/api/v1/generate -H 'Content-Type: application/json' \
    -d '{"idempotency_key":"cost-in","event_type":"input_token","quantity":1000}'
... "event_type":"input_token","quantity":1000,"cost_cents":1 ...

$ curl -s -X POST localhost:8000/api/v1/generate -H 'Content-Type: application/json' \
    -d '{"idempotency_key":"cost-out","event_type":"output_token","quantity":3000}'
... "event_type":"output_token","quantity":3000,"cost_cents":9 ...

$ curl -s localhost:8000/api/v1/usage/<tenant_id>
{"api_calls_used":48,"tokens_used":4000,"total_cost_cents":10,...}   # 1¢ + 9¢ = 10¢
```
Proof of the formula: `tokens_to_cents(qty, type)` floors to whole thousands × rate, all integers — no float touches money.

---

## 4. Stripe integration — checkout, verified webhook, dedupe, plan sync

**Checkout session created via the app with correct tenant metadata:**
```
$ curl -s -X POST localhost:8000/api/v1/checkout -H 'Content-Type: application/json' \
    -d '{"tenant_id":"7fb45d71-...","plan_id":"a27e5dd3-..."}'
{"session_id":"cs_test_a1CmnU...","url":"https://checkout.stripe.com/c/pay/cs_test_a1CmnU..."}
```
Confirmed in Stripe API: `mode: subscription`, `metadata: {tenant_id, plan_id}` — so the webhook knows which tenant to upgrade.

**Forged webhook → 400 (nothing changes):**
```
$ curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/webhooks/stripe \
    -H 'stripe-signature: garbage' -H 'Content-Type: application/json' \
    -d '{"type":"checkout.session.completed","data":{"object":{}}}'
400
```
Signature is verified FIRST; a bad signature is rejected before any processing.

**Free → Pro flip via the webhook worker (PROBE 3):**
Driving the exact task the webhook enqueues with a `checkout.session.completed` payload
carrying `metadata.tenant_id`:
```
before: plan_status = free

TASK RESULT: {'status': 'subscription_updated', 'tenant_id': '7fb45d71-...'}

after:  plan_status = pro, stripe_subscription_id = sub_e2e_probe3
        payment_records: one row (evt_e2e_probe3, checkout.session.completed)
```

**Replay dedupe (PROBE 4) — same event id processed once:**
```
REPLAY RESULT: {'status': 'already_processed', 'event_id': 'evt_e2e_probe3'}
-> tenant still 'pro'; stripe_subscription_id NOT overwritten; exactly 1 payment_record
```
`payment_records.stripe_event_id` is `UNIQUE` — a replayed event is a no-op (still 200 so Stripe stops retrying).

**Webhook returns immediately (enqueue, not sync) → 200:**
```
$ stripe listen --forward-to localhost:8000/webhooks/stripe
2026-08-31  --> checkout.session.completed [evt_1UAZdW...]
2026-08-31  <-- [200] POST http://localhost:8000/webhooks/stripe
```
The handler verifies the signature, enqueues `billing.process_stripe_event` on Celery,
and returns 200. The worker runs the dedupe + plan sync off the request path.

**Dedupe:** `payment_records.stripe_event_id` is `UNIQUE` — a replayed event id is a no-op
(`already_processed`), and the handler still returns 200 so Stripe stops retrying.

---

## 5. Persistence & isolation — schema as migrations, tenant isolation

Schema is created by Alembic migration (`migrations/versions/0001_initial.py`), not raw
`CREATE TABLE`. Tables confirmed in Postgres:
```
plans, tenants, usage_events, monthly_rollups, subscriptions, payment_records
```
Every usage event, rollup, and subscription carries `tenant_id`; all queries filter by it
(`WHERE tenant_id = ?`) — one tenant can never see another's data.

---

## 6. Background job (Shared Requirement #3)

`POST /webhooks/stripe` → verify sig → **enqueue Celery → return 200**. The worker
(`billing.process_stripe_event`) opens its own DB session, dedupes by event id, and syncs
the tenant plan/status — **never in the request path**. Worker retries with backoff.
```
$ celery -A app.workers.celery_app.celery_app worker --loglevel=info
[2026-08-31] celery@Mazen ready.
```

---

## 7. Validation at the boundary — clean 4xx, never 500

Bad input is rejected by Pydantic before any logic runs:
```
$ curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/api/v1/generate \
    -H 'Content-Type: application/json' -d '{"event_type":"api_call"}'        # missing quantity
422
$ curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/api/v1/generate \
    -H 'Content-Type: application/json' -d '{"event_type":"bogus","quantity":1,"idempotency_key":"x"}'
422
```
No `500` for user error.
